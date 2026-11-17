"""Read-only opt-in checks. Never create a PR or deploy production from tests."""
import os

import pytest

from healing.config import Settings


@pytest.mark.live
@pytest.mark.skipif(os.getenv("RUN_LIVE_TESTS") != "1", reason="Set RUN_LIVE_TESTS=1 with provider credentials")
async def test_live_scalingo_and_github_reads():
    from healing.adapters.github import GitHubAdapter
    from healing.adapters.scalingo import ScalingoAdapter
    settings = Settings()
    assert not settings.demo_mode, "Live checks require DEMO_MODE=false"
    scalingo = ScalingoAdapter(settings)
    github = GitHubAdapter(settings)
    try:
        app = await scalingo.get_application()
        assert app
        assert len(await github.base_commit()) == 40
    finally:
        for adapter in [scalingo, github]:
            if hasattr(adapter, "close"):
                await adapter.close()
