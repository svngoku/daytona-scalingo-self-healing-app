import asyncio
import json
import tarfile
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from healing.adapters.base import AdapterError, validate_files
from healing.adapters.github import GitHubAdapter
from healing.adapters.sandbox import DaytonaSandboxManager, DockerSandboxManager, _package_demo_source
from healing.adapters.scalingo import ScalingoAdapter

BASE = "1" * 40
TREE = "2" * 40
PATCH_TREE = "3" * 40
PATCH = "4" * 40
FILE = "apps/broken-app/main.py"


@pytest.mark.parametrize("path", ["/apps/broken-app/main.py", "apps/broken-app/../bad.py",
                                  "apps/broken-app/link/../../bad.py", "apps/broken-app/main.sh",
                                  "apps/broken-app/.git/main.py", "apps/dashboard/main.py"])
def test_patch_validation_rejects_out_of_scope_paths(path):
    with pytest.raises(ValueError):
        validate_files({path: "pass\n"})


def settings(**overrides):
    data = {
        "demo_mode": False,
        "github_owner": "demo-owner",
        "github_repository": "demo-repo",
        "github_allowed_repositories": ["demo-owner/demo-repo"],
        "github_default_branch": "main",
        "github_token": "example",
        "github_dry_run": False,
        "github_write_enabled": True,
        "scalingo_api_token": "example",
        "scalingo_app_name": "example-app",
        "scalingo_api_url": "https://api.osc-fr1.scalingo.com",
        "command_timeout_seconds": 30,
        "sandbox_timeout_seconds": 60,
    }
    return SimpleNamespace(**(data | overrides))


def test_dry_run_omits_fabricated_github_identifiers():
    adapter = GitHubAdapter(settings(github_dry_run=True))
    result = asyncio.run(adapter.create_pull_request("one", BASE, {FILE: "pass\n"}, {}, False))
    assert result == {"url": None, "number": None, "branch": "fix/incident-one", "commit": None, "dry_run": True}


@pytest.mark.parametrize(
    ("authorized", "writes", "allowed"),
    [(False, True, ["demo-owner/demo-repo"]), (True, False, ["demo-owner/demo-repo"]), (True, True, [])],
)
def test_github_requires_approval_write_flag_and_allowlist(authorized, writes, allowed):
    def no_request(request):
        pytest.fail("Policy must be evaluated before a GitHub request")

    async def check():
        async with httpx.AsyncClient(transport=httpx.MockTransport(no_request)) as client:
            adapter = GitHubAdapter(settings(github_write_enabled=writes, github_allowed_repositories=allowed), client)
            with pytest.raises(PermissionError):
                await adapter.create_pull_request("one", BASE, {FILE: "pass\n"}, {}, authorized)

    asyncio.run(check())


def test_github_creates_only_fix_ref_and_reuses_same_pull_request():
    changes = {FILE: "pass\n"}
    writes = []
    branch_exists = False
    pull_exists = False
    pull_response = {"html_url": "https://github.com/demo-owner/demo-repo/pull/42", "number": 42, "head": {"sha": PATCH}}

    def api(request):
        nonlocal branch_exists, pull_exists
        assert request.headers["x-github-api-version"] == "2026-03-10"
        path = request.url.path.removeprefix("/repos/demo-owner/demo-repo")
        if request.method == "GET":
            if path == "/git/ref/heads/main":
                return httpx.Response(200, json={"object": {"sha": BASE}})
            if path == f"/git/commits/{BASE}":
                return httpx.Response(200, json={"tree": {"sha": TREE}})
            if path == f"/git/trees/{TREE}":
                return httpx.Response(200, json={"tree": [{"path": FILE, "mode": "100644"}], "truncated": False})
            if path == "/git/ref/heads/fix/incident-one":
                return httpx.Response(200, json={"object": {"sha": PATCH}}) if branch_exists else httpx.Response(404)
            if path == f"/git/commits/{PATCH}":
                return httpx.Response(200, json={"tree": {"sha": PATCH_TREE}, "parents": [{"sha": BASE}]})
            if path == "/pulls":
                return httpx.Response(200, json=[pull_response] if pull_exists else [])
        assert request.method == "POST"
        payload = json.loads(request.content)
        writes.append(path)
        if path == "/git/trees":
            assert payload == {
                "base_tree": TREE, "tree": [{"path": FILE, "mode": "100644", "type": "blob", "content": "pass\n"}],
            }
            return httpx.Response(201, json={"sha": PATCH_TREE})
        if path == "/git/commits":
            assert payload["parents"] == [BASE]
            return httpx.Response(201, json={"sha": PATCH})
        if path == "/git/refs":
            assert payload == {"ref": "refs/heads/fix/incident-one", "sha": PATCH}
            branch_exists = True
            return httpx.Response(201, json=payload)
        if path == "/pulls":
            assert payload["head"] == "fix/incident-one" and payload["base"] == "main"
            assert "Zero quantity" in payload["body"]
            assert FILE in payload["body"]
            assert "test_zero_quantity_returns_400" in payload["body"]
            assert "Exit status 1" in payload["body"] and "Exit status 0" in payload["body"]
            assert "Pending deployment" in payload["body"]
            assert "[REDACTED]" in payload["body"] and "ghp_secretfordemo" not in payload["body"]
            pull_exists = True
            return httpx.Response(201, json=pull_response)
        pytest.fail(f"Unexpected {request.method} {path}")

    async def check():
        async with httpx.AsyncClient(transport=httpx.MockTransport(api)) as client:
            adapter = GitHubAdapter(settings(), client)
            assert await adapter.base_commit() == BASE
            report = {
                "root_cause": "Zero quantity",
                "commands": [
                    {"command": "pytest -k test_zero_quantity_returns_400", "exit_code": 1,
                     "stdout": "logged ghp_secretfordemo"},
                    {"command": "pytest apps/broken-app/tests", "exit_code": 0, "stdout": "3 passed"},
                ],
            }
            first = await adapter.create_pull_request("one", BASE, changes, report, True)
            second = await adapter.create_pull_request("one", BASE, changes, report, True)
            assert first == second
            assert first["number"] == 42 and first["commit"] == PATCH and not first["dry_run"]
            assert writes == ["/git/trees", "/git/commits", "/git/refs", "/pulls", "/git/trees"]

    asyncio.run(check())


def test_scalingo_runtime_logs_and_review_app_use_regional_api():
    exchange_count = 0

    def api(request):
        nonlocal exchange_count
        host, path = request.url.host, request.url.path
        if host == "auth.scalingo.com":
            assert request.method == "POST" and path == "/v1/tokens/exchange"
            assert request.headers["authorization"] == "Basic OmV4YW1wbGU="
            exchange_count += 1
            return httpx.Response(200, json={"token": "short-lived"})
        if host == "logs.shard-0.osc-fr1.scalingo.com":
            assert "authorization" not in request.headers
            assert dict(request.url.params) == {"token": "signed", "n": "200", "stream": "false"}
            return httpx.Response(200, text="Runtime event incident-123\nTraceback\nZeroDivisionError\n")
        assert host == "api.osc-fr1.scalingo.com"
        assert request.headers["authorization"] == "Bearer short-lived"
        if path == "/v1/apps/example-app/logs":
            return httpx.Response(
                200, json={"logs_url": "https://logs.shard-0.osc-fr1.scalingo.com/apps/example-app/logs?token=signed"}
            )
        if path == "/v1/apps/example-app/scm_repo_link/review_apps":
            return httpx.Response(200, json={"review_apps": [{
                "app_name": "example-app-pr42", "pull_request": {"number": 42},
                "last_deployment": {"status": "success"},
            }]})
        if path == "/v1/apps/example-app-pr42":
            return httpx.Response(200, json={"app": {"url": "https://example-app-pr42.osc-fr1.scalingo.io"}})
        pytest.fail(f"Unexpected {request.method} {path}")

    async def check():
        async with httpx.AsyncClient(transport=httpx.MockTransport(api)) as client:
            adapter = ScalingoAdapter(settings(), client)
            assert "ZeroDivisionError" in await adapter.fetch_recent_logs("incident-123")
            assert await adapter.get_review_app_status(1) == {"status": "pending", "app_name": None, "url": None}
            assert await adapter.get_review_app_status(42) == {
                "status": "ready", "app_name": "example-app-pr42",
                "url": "https://example-app-pr42.osc-fr1.scalingo.io",
            }

    asyncio.run(check())
    assert exchange_count == 1


def test_unexpected_scalingo_logs_destination_is_rejected():
    adapter = ScalingoAdapter(settings())
    with pytest.raises(AdapterError, match="unexpected application logs URL"):
        asyncio.run(adapter._download_logs("https://logs.scalingo.com.example.test/path?token=sensitive"))


def test_sandbox_rejects_arbitrary_command_before_calling_provider():
    sandbox = DockerSandboxManager(settings())
    with pytest.raises(ValueError, match="Sandbox action"):
        asyncio.run(sandbox.run("sh -c whoami"))


@pytest.mark.parametrize("install_fails", [False, True])
def test_daytona_sdk_lifecycle_keeps_created_sandbox_available_for_cleanup(monkeypatch, install_fails):
    daytona = pytest.importorskip("daytona")
    calls = []

    class SDKDouble:
        def __init__(self, config):
            assert isinstance(config, daytona.DaytonaConfig)
            assert config.api_key == "daytona-example"

        def create(self, params, *, timeout):
            assert isinstance(params, daytona.CreateSandboxFromImageParams)
            assert params.image == "python:3.12-bookworm"
            assert not params.public and params.ephemeral and params.ttl_minutes > 0
            assert not params.env_vars and not params.secrets
            assert timeout == 60
            calls.append("created")
            return SimpleNamespace(
                id="sandbox-id", process=SimpleNamespace(exec=execute), update_network_settings=network
            )

        def delete(self, sandbox, timeout, wait):
            assert sandbox.id == "sandbox-id" and timeout == 30 and wait
            calls.append("deleted")

    def execute(command, *, cwd, timeout):
        assert cwd.startswith("/tmp") and timeout in {35, 65}
        assert "github-write-token" not in command
        if " fetch " in command:
            assert "https://github.com/demo-owner/demo-repo.git" in command and BASE in command
            calls.append("fetched")
        if "rev-parse HEAD" in command:
            return SimpleNamespace(result=f"{BASE}\n", exit_code=0)
        if "pip --isolated install" in command:
            calls.append("installed")
            return SimpleNamespace(result="", exit_code=int(install_fails))
        if "-m pytest" in command:
            assert calls[-1] == "network blocked"
            calls.append("tested")
        return SimpleNamespace(result="", exit_code=0)

    def network(*, network_block_all, request_timeout):
        assert network_block_all and request_timeout == 30
        calls.append("network blocked")

    monkeypatch.setattr(daytona, "Daytona", SDKDouble)
    manager = DaytonaSandboxManager(settings(
        sandbox_image="python:3.12-bookworm", daytona_api_key="daytona-example",
        daytona_api_url="https://app.daytona.io/api", github_token="github-write-token",
    ))

    async def check():
        try:
            if install_fails:
                with pytest.raises(AdapterError, match="install baseline dependencies"):
                    await manager.create("one", BASE)
            else:
                info = await manager.create("one", BASE)
                assert (info.id, info.provider, info.status) == ("sandbox-id", "daytona", "ready")
                assert (await manager.run("tests")).exit_code == 0
        finally:
            await manager.cleanup()
        await manager.cleanup()

    asyncio.run(check())
    assert calls[:3] == ["created", "fetched", "installed"]
    assert calls[3:] == (["deleted"] if install_fails else ["network blocked", "tested", "deleted"])


def test_local_source_copy_excludes_secrets_and_symlinks(tmp_path: Path):
    source = tmp_path / "repo"
    app = source / "apps" / "broken-app"
    app.mkdir(parents=True)
    (app / ".env").write_text("secret data")
    (app / "main.py").write_text("pass\n")
    (app / "requirements.txt").write_text("")
    (app / "bad.py").symlink_to(app / ".env")
    with tarfile.open(_package_demo_source(source, tmp_path)) as archive:
        assert archive.getnames() == [
            "apps", "apps/broken-app", "apps/broken-app/main.py", "apps/broken-app/requirements.txt",
        ]
        assert all(member.uid == member.gid == 0 for member in archive)
        assert archive.getmember("apps/broken-app/main.py").mode == 0o644
