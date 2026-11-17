import asyncio
import importlib.util
import os
from pathlib import Path

import httpx
import pytest

from healing.config import Settings
from healing.models import Diagnosis, RepairReport, State, validate_transition
from healing.store import Store
from healing.workflow import Workflow


class Result:
    def __init__(self, code=0, stdout=""):
        self.command, self.stdout, self.stderr, self.exit_code = "pytest", stdout, "", code

    def to_dict(self):
        return vars(self)


class Sandbox:
    def __init__(self, failures=0):
        self.fixed = False
        self.cleaned = False
        self.failures = failures
        self.calls = 0

    async def create(self, *args):
        from healing.adapters.base import SandboxInfo
        return SandboxInfo("test-isolation", "mock", "running")

    async def read_files(self, paths):
        return {path: "immutable test" for path in paths}

    async def write_files(self, files):
        pass

    async def run(self, action):
        if action == "inspect":
            return Result(stdout="apps/broken-app/main.py\napps/broken-app/tests/test_quote.py\n")
        if not self.fixed:
            return Result(1, "test_zero_quantity_returns_400 AssertionError: assert 500 == 400")
        if action == "tests":
            self.calls += 1
            if self.calls <= self.failures:
                return Result(1, "a distinct regression failed")
        return Result(stdout="4 passed")

    async def diff(self):
        return "--- a/apps/broken-app/main.py\n+++ b/apps/broken-app/main.py\n+validated change"

    async def changed_files(self):
        return {"apps/broken-app/main.py": "validated change"}

    async def cleanup(self):
        self.cleaned = True


class Agent:
    async def diagnose(self, logs):
        return Diagnosis(summary="Test diagnosis", root_cause="Observed error", confidence=0.9)

    async def repair(self, sandbox, context, emit):
        sandbox.fixed = True
        return RepairReport(summary="Test report", root_cause="Observed error", confidence=0.9,
                            correction="Test correction", regression_tests=["test"],
                            validation_summary="pending", files_changed=[])


class Scalingo:
    async def fetch_recent_logs(self, correlation):
        return f"{correlation} ZeroDivisionError traceback"

    async def get_review_app_status(self, number):
        return {"status": "ready", "url": "https://preview.osc-fr1.scalingo.io", "app_name": "preview"}


class GitHub:
    def __init__(self, dry_run=True):
        self.dry_run = dry_run
        self.calls = []

    async def base_commit(self):
        return "a" * 40

    async def create_pull_request(self, *args, authorized):
        self.calls.append(authorized)
        return {"dry_run": self.dry_run, "number": None if self.dry_run else 12,
                "url": None if self.dry_run else "https://github.com/example/app/pull/12"}


def setup_workflow(tmp_path, *, failures=0, live=False, handler=None):
    settings = Settings(_env_file=None, database_url="sqlite:///:memory:",
                        demo_mode=not live, agent_mode="openrouter" if live else "fixture",
                        orchestrator_api_token="test-token" if live else "", github_dry_run=not live,
                        github_write_enabled=live, review_poll_seconds=0.01)
    store = Store(":memory:")
    sandbox = Sandbox(failures)
    github = GitHub(not live)
    def default_handler(request):
        if request.url.host == "127.0.0.1":
            return httpx.Response(500)
        return httpx.Response(400 if "quantity=0" in str(request.url) else 200,
                              json={"detail": "Invalid quantity"})
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler or default_handler))
    flow = Workflow(settings, store, http=client, sandbox_factory=lambda: sandbox,
                    agent_factory=Agent, scalingo=Scalingo(), github=github)
    return settings, store, sandbox, github, flow, client


async def settled(flow):
    await asyncio.gather(*list(flow.tasks.values()))
    await asyncio.sleep(0)


def test_state_machine_rejects_unearned_success():
    with pytest.raises(ValueError):
        validate_transition(State.INCIDENT_DETECTED, State.COMPLETED)
    with pytest.raises(ValueError):
        validate_transition(State.CANCELLED, State.PR_CREATING)
    with pytest.raises(ValueError):
        validate_transition(State.COMPLETED, State.FAILED)
    validate_transition(State.RUNNING_TESTS, State.RETRYING)


def test_store_persists_ordered_events_and_replay(tmp_path):
    path = str(tmp_path / "events.db")
    store = Store(path)
    incident = store.create()
    store.update(incident.id, state=State.INCIDENT_DETECTED, summary="Observed HTTP500", outputs={"status": 500})
    store.update(incident.id, state=State.LOGS_COLLECTED, summary="Collected evidence")
    cursor = store.events(incident.id)[0].id
    store.close()
    restored = Store(path)
    assert restored.get(incident.id).state == State.LOGS_COLLECTED
    assert len(restored.events(incident.id, cursor)) == 1
    restored.close()


async def test_successful_dry_run_does_not_invent_preview(tmp_path):
    _, store, sandbox, github, flow, client = setup_workflow(tmp_path)
    incident = await flow.start()
    await settled(flow)
    result = store.get(incident.id)
    assert result.state == State.PR_CREATING
    assert result.artifacts["tests_passed"] and result.artifacts["reproduced"]
    assert result.artifacts["publication_status"] == "dry_run"
    assert not result.artifacts["preview_validated"]
    assert sandbox.cleaned and github.calls == [False]
    await client.aclose()


async def test_three_attempt_bound_and_cleanup(tmp_path):
    _, store, sandbox, github, flow, client = setup_workflow(tmp_path, failures=10)
    incident = await flow.start()
    await settled(flow)
    assert store.get(incident.id).state == State.FAILED
    assert store.get(incident.id).attempt == 3
    assert "All three repair attempts failed" in store.get(incident.id).error
    assert store.get(incident.id).summary == "Incident investigation stopped"
    assert store.events(incident.id)[-1].summary == "Sandbox cleaned up"
    assert sandbox.cleaned and not github.calls
    with pytest.raises(ValueError, match="exhausted"):
        await flow.retry(incident.id)
    await client.aclose()


async def test_retry_refreshes_correlation_and_clears_stale_artifacts(tmp_path):
    _, store, _, _, flow, client = setup_workflow(tmp_path)
    incident = store.create()
    store.update(incident.id, state=State.FAILED, summary="Previous failure",
                 error="Previous failure", attempt=1, artifacts={"obsolete": True})
    retried = await flow.retry(incident.id)
    assert retried.correlation_id != incident.correlation_id
    assert not retried.artifacts
    await settled(flow)
    assert store.get(incident.id).attempt == 2
    assert store.get(incident.id).artifacts["tests_passed"]
    await client.aclose()


async def test_test_run_cannot_mutate_existing_regression(tmp_path):
    _, store, _, github, flow, client = setup_workflow(tmp_path)

    class MutatingSandbox(Sandbox):
        def __init__(self):
            super().__init__()
            self.changed = False

        async def read_files(self, paths):
            return {path: "changed test" if self.changed else "immutable test" for path in paths}

        async def run(self, action):
            result = await super().run(action)
            if action == "tests":
                self.changed = True
            return result

        async def write_files(self, files):
            self.changed = False

    flow.sandbox_factory = MutatingSandbox
    incident = await flow.start()
    await settled(flow)
    result = store.get(incident.id)
    assert result.state == State.FAILED
    assert "Sandbox tests modified the original regression tests" in result.error
    assert not github.calls
    await client.aclose()


async def test_persisted_artifact_evidence_is_redacted(tmp_path):
    settings, store, _, _, flow, client = setup_workflow(tmp_path)
    settings.openrouter_api_key = "test-confidential-value"
    incident = store.create()
    flow.emit(incident.id, "Received provider evidence", artifacts={"provider": settings.openrouter_api_key})
    assert store.get(incident.id).artifacts["provider"] == "[REDACTED]"
    await client.aclose()


async def test_transient_test_failure_returns_evidence_then_recovers(tmp_path):
    _, store, sandbox, _, flow, client = setup_workflow(tmp_path, failures=1)
    incident = await flow.start()
    await settled(flow)
    assert store.get(incident.id).attempt == 2
    assert store.get(incident.id).artifacts["tests_passed"]
    assert any(event.state == State.RETRYING for event in store.events(incident.id))
    assert sandbox.cleaned
    await client.aclose()


async def test_next_repair_attempt_can_read_new_files_from_the_previous_attempt(tmp_path):
    new_file = "apps/broken-app/tests/test_new.py"
    source = 'def test_new():\n    assert True\n'
    _, store, _, _, flow, client = setup_workflow(tmp_path)

    class WorktreeSandbox(Sandbox):
        def __init__(self):
            super().__init__(failures=1)
            self.files = {"apps/broken-app/tests/test_quote.py": "immutable test"}

        async def write_files(self, files):
            self.files.update(files)

        async def read_files(self, paths):
            return {path: self.files[path] for path in paths}

        async def run(self, action):
            if action == "inspect":
                return Result(stdout="\n".join(["apps/broken-app/main.py", *self.files]))
            return await super().run(action)

    class RevisingAgent(Agent):
        async def repair(self, sandbox, context, emit):
            listed = set(context["files"].splitlines())
            if context["attempt"] == 1:
                assert new_file not in listed
                await sandbox.write_files({new_file: source})
            else:
                assert new_file in listed
                assert new_file not in context["protected_tests"]
                assert await sandbox.read_files([new_file]) == {new_file: source}
                assert "a distinct regression failed" in context["failed_tests"]
            return await super().repair(sandbox, context, emit)

    flow.sandbox_factory = WorktreeSandbox
    flow.agent_factory = RevisingAgent
    try:
        incident = await flow.start()
        await settled(flow)
        result = store.get(incident.id)
        assert result.state == State.PR_CREATING, result.error
        assert result.attempt == 2
        assert result.artifacts["tests_passed"]
    finally:
        await client.aclose()


async def test_github_requires_explicit_incident_authorization(tmp_path):
    _, store, sandbox, github, flow, client = setup_workflow(tmp_path, live=True)
    incident = await flow.start()
    await settled(flow)
    assert not github.calls and sandbox.cleaned
    assert store.get(incident.id).artifacts["authorization_required"]
    await flow.authorize(incident.id)
    await settled(flow)
    result = store.get(incident.id)
    assert github.calls == [True] and result.state == State.AWAITING_APPROVAL
    assert result.artifacts["preview_validated"] and not result.artifacts["merged"]
    await client.aclose()


async def test_preview_failure_never_reports_resolved(tmp_path):
    def handler(request):
        return httpx.Response(500)
    _, store, _, _, flow, client = setup_workflow(tmp_path, live=True, handler=handler)
    incident = await flow.start()
    await settled(flow)
    await flow.authorize(incident.id)
    await settled(flow)
    assert store.get(incident.id).state == State.FAILED
    assert not store.get(incident.id).artifacts["preview_validated"]
    await client.aclose()


async def test_cancel_stops_active_work_and_cleans_sandbox(tmp_path):
    _, store, sandbox, _, flow, client = setup_workflow(tmp_path)
    entered = asyncio.Event()
    class SlowAgent(Agent):
        async def repair(self, *args):
            entered.set()
            await asyncio.Event().wait()
    flow.agent_factory = SlowAgent
    incident = await flow.start()
    await asyncio.wait_for(entered.wait(), 5)
    await flow.cancel(incident.id)
    assert store.get(incident.id).state == State.CANCELLED
    assert sandbox.cleaned
    await client.aclose()


async def test_api_real_http_failure_and_secret_redaction(tmp_path, monkeypatch):
    monkeypatch.setenv("LOG_PATH", str(tmp_path / "broken.jsonl"))
    service_path = Path(__file__).resolve().parents[1] / "apps/broken-app/main.py"
    spec = importlib.util.spec_from_file_location("pricing_for_api_test", service_path)
    service = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(service)
    settings, store, sandbox, github, flow, client = setup_workflow(tmp_path)
    await client.aclose()
    flow.http = httpx.AsyncClient(transport=httpx.ASGITransport(app=service.app, raise_app_exceptions=False),
                                 base_url="http://127.0.0.1:8001")
    from healing.main import create_app
    app = create_app(settings, store, flow)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as api:
        response = await api.post("/api/incidents")
        assert response.status_code == 202
        await settled(flow)
        result = (await api.get("/api/incidents/" + response.json()["id"])).json()
        assert result["artifacts"]["http_status"] == 500
        assert "validated_changes" not in result["artifacts"]
        assert result["state"] == "PR_CREATING"
        assert (await api.get("/api/incidents/missing")).status_code == 404
    assert sandbox.cleaned
    await flow.http.aclose()


async def test_api_auth_and_reject_bad_sse_cursor(tmp_path):
    settings, store, _, _, flow, client = setup_workflow(tmp_path, live=True)
    from healing.main import create_app
    app = create_app(settings, store, flow)
    incident = store.create()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as api:
        assert (await api.get("/api/incidents")).status_code == 401
        invalid = await api.get("/api/incidents", headers=[(b"x-orchestrator-token", b"\xff")])
        assert invalid.status_code == 401
        response = await api.get(f"/api/incidents/{incident.id}/events",
                                 headers={"X-Orchestrator-Token": "test-token", "Last-Event-ID": "abc"})
        assert response.status_code == 400
    await client.aclose()


def test_live_config_rejects_fixture_and_missing_auth():
    with pytest.raises(ValueError):
        Settings(_env_file=None, demo_mode=False)


@pytest.mark.docker
@pytest.mark.skipif(os.getenv("RUN_DOCKER_TESTS") != "1", reason="Set RUN_DOCKER_TESTS=1 for actual Docker repair")
async def test_real_local_end_to_end(tmp_path, monkeypatch):
    from healing.adapters.sandbox import create_sandbox_manager
    from healing.adapters.scalingo import ScalingoAdapter
    from healing.demo_fixture import FixtureAgent
    monkeypatch.setenv("LOG_PATH", str(tmp_path / "real.jsonl"))
    path = Path(__file__).resolve().parents[1] / "apps/broken-app/main.py"
    spec = importlib.util.spec_from_file_location("pricing_docker_e2e", path)
    service = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(service)
    settings = Settings(_env_file=None, database_url="sqlite:///:memory:",
                        local_logs_path=tmp_path / "real.jsonl", sandbox_timeout_seconds=900)
    store = Store(":memory:")
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=service.app, raise_app_exceptions=False))
    flow = Workflow(settings, store, http=client, sandbox_factory=lambda: create_sandbox_manager(settings),
                    agent_factory=FixtureAgent, scalingo=ScalingoAdapter(settings))
    incident = await flow.start()
    await settled(flow)
    result = store.get(incident.id)
    assert result.state == State.PR_CREATING, result.model_dump_json()
    assert result.artifacts["tests_passed"]
    assert result.artifacts["reproduced"]
    assert result.artifacts["sandbox"]["status"] == "destroyed"
    assert result.artifacts["publication_status"] == "dry_run"
    await flow.close()
    await client.aclose()
