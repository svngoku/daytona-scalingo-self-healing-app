from pathlib import Path
from typing import Literal

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
OPENROUTER_DEFAULT_MODEL = "openai/gpt-5-mini"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", enable_decoding=False)

    demo_mode: bool = True
    agent_mode: Literal["fixture", "openrouter"] = "fixture"
    sandbox_provider: Literal["docker", "daytona"] = "docker"
    openrouter_api_key: str = ""
    openrouter_model: str = OPENROUTER_DEFAULT_MODEL
    openrouter_base_url: str = OPENROUTER_BASE_URL
    daytona_api_key: str = ""
    daytona_api_url: str = "https://app.daytona.io/api"
    sandbox_image: str = "python:3.12-bookworm"
    sandbox_timeout_seconds: int = 600
    command_timeout_seconds: int = 120
    docker_binary: str = "docker"
    scalingo_api_token: str = ""
    scalingo_app_name: str = ""
    scalingo_api_url: str = "https://api.osc-fr1.scalingo.com"
    github_token: str = ""
    github_owner: str = ""
    github_repository: str = ""
    github_default_branch: str = "main"
    github_allowed_repositories: list[str] = []
    github_write_enabled: bool = False
    github_dry_run: bool = True
    orchestrator_api_token: str = ""
    database_url: str = "sqlite:///.data/incidents.db"
    broken_app_url: str = "http://127.0.0.1:8001"
    local_logs_path: Path = Path(".data/broken-app.jsonl")
    repo_root: Path = Path(__file__).resolve().parents[3]
    cors_origins: list[str] = ["http://localhost:3000", "http://127.0.0.1:3000"]
    review_timeout_seconds: int = 600
    review_poll_seconds: float = 5
    review_allowed_hosts: list[str] = []

    @field_validator("github_allowed_repositories", "cors_origins", "review_allowed_hosts", mode="before")
    @classmethod
    def split_list(cls, value):
        return [part.strip() for part in value.split(",") if part.strip()] if isinstance(value, str) else value

    @field_validator("openrouter_base_url")
    @classmethod
    def openrouter_endpoint(cls, value: str) -> str:
        if value.rstrip("/") != OPENROUTER_BASE_URL:
            raise ValueError("OPENROUTER_BASE_URL must be https://openrouter.ai/api/v1")
        return OPENROUTER_BASE_URL

    @field_validator("openrouter_model")
    @classmethod
    def openrouter_model_id(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("OPENROUTER_MODEL must name a model in the OpenRouter catalog")
        return value.strip()

    @model_validator(mode="after")
    def safe_configuration(self):
        if not self.demo_mode and (self.agent_mode == "fixture" or not self.orchestrator_api_token):
            raise ValueError("Live mode requires AGENT_MODE=openrouter and ORCHESTRATOR_API_TOKEN")
        if self.demo_mode and not self.github_dry_run:
            raise ValueError("Local demo requires GITHUB_DRY_RUN=true; live writes require DEMO_MODE=false")
        if not self.database_url.startswith("sqlite:///"):
            raise ValueError("Only sqlite:/// DATABASE_URL is supported")
        if min(self.sandbox_timeout_seconds, self.command_timeout_seconds, self.review_timeout_seconds) < 1:
            raise ValueError("Timeouts must be positive")
        if self.review_poll_seconds < 0.01:
            raise ValueError("Review polling must be at least 0.01 seconds")
        self.repo_root = self.repo_root.resolve()
        return self

    @property
    def database_path(self) -> str:
        return self.database_url.removeprefix("sqlite:///")

    @property
    def secrets(self) -> list[str]:
        values = (self.openrouter_api_key, self.daytona_api_key, self.scalingo_api_token,
                  self.github_token, self.orchestrator_api_token)
        return sorted({value for value in values if value}, key=len, reverse=True)
