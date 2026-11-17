from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from healing.adapters.github import DEMO_COMMIT, GitHubAdapter
from healing.config import Settings
from healing.main import create_app


@pytest.mark.parametrize("provider", ["docker", "daytona"])
async def test_local_staging_selects_checkout_by_sandbox_provider(provider):
    base_sha = "a" * 40
    requests = []

    def handler(request):
        requests.append(request)
        assert request.method == "GET"
        assert request.url == httpx.URL("https://api.github.com/repos/demo-owner/demo-repo/git/ref/heads/main")
        return httpx.Response(200, json={"object": {"sha": base_sha}})

    settings = Settings(
        _env_file=None,
        demo_mode=True,
        sandbox_provider=provider,
        github_owner="demo-owner",
        github_repository="demo-repo",
        github_allowed_repositories=["demo-owner/demo-repo"],
        github_dry_run=True,
        github_write_enabled=True,
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        github = GitHubAdapter(settings, client)
        base = await github.base_commit()
        proposal = await github.create_pull_request(
            "hybrid", base, {"apps/broken-app/main.py": "pass\n"}, {}, authorized=True
        )
    assert (base, len(requests)) == ((DEMO_COMMIT, 0) if provider == "docker" else (base_sha, 1))
    assert proposal["dry_run"] and proposal["number"] is None


async def test_local_staging_reports_configured_daytona(tmp_path):
    settings = Settings(
        _env_file=None,
        demo_mode=True,
        sandbox_provider="daytona",
        daytona_api_key="synthetic-daytona-credential",
        github_dry_run=True,
        database_url=f"sqlite:///{tmp_path / 'incidents.db'}",
    )
    health = AsyncMock(return_value=SimpleNamespace(status_code=200))
    app = create_app(settings, workflow=SimpleNamespace(http=SimpleNamespace(get=health)))
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/api/status")
    finally:
        app.state.store.close()
    assert response.status_code == 200
    status = response.json()
    assert status["mode"] == "local"
    assert status["providers"]["daytona"]["status"] == "configured"
    assert status["providers"]["scalingo"]["status"] == "local"
    assert status["providers"]["github"]["status"] == "dry_run"
    assert settings.daytona_api_key not in response.text
