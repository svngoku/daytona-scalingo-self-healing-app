from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Protocol

APP_PATH = "apps/broken-app"
MAX_FILES = 8
MAX_FILE_BYTES = 32_768
OUTPUT_LIMIT = 262_144
OUTPUT_TRUNCATED = "\n[output truncated]"
SAFE_PART = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.-]*\Z")


class AdapterError(RuntimeError):
    """A provider operation could not be completed."""


class GitHubSettings(Protocol):
    demo_mode: bool
    sandbox_provider: str
    github_token: str | None
    github_owner: str
    github_repository: str
    github_default_branch: str
    github_allowed_repositories: list[str]
    github_write_enabled: bool
    github_dry_run: bool


class SandboxSettings(GitHubSettings, Protocol):
    daytona_api_key: str | None
    daytona_api_url: str | None
    sandbox_image: str
    sandbox_timeout_seconds: int
    command_timeout_seconds: int
    repo_root: Path


class ScalingoSettings(Protocol):
    demo_mode: bool
    scalingo_api_token: str | None
    scalingo_app_name: str
    scalingo_api_url: str
    broken_app_url: str
    local_logs_path: Path


@dataclass(frozen=True, slots=True)
class CommandResult:
    command: str
    stdout: str
    stderr: str
    exit_code: int

    def to_dict(self) -> dict[str, str | int]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class SandboxInfo:
    id: str
    provider: str
    status: str


def validate_python_path(path: str) -> None:
    if (
        not path.startswith(f"{APP_PATH}/")
        or not path.endswith(".py")
        or len(path) > 256
        or any(not SAFE_PART.fullmatch(part) for part in path.split("/"))
    ):
        raise ValueError("Only safe Python paths under apps/broken-app are allowed")


def validate_files(files: dict[str, str]) -> None:
    if len(files) > MAX_FILES:
        raise ValueError(f"A repair may change at most {MAX_FILES} files")
    for path, content in files.items():
        validate_python_path(path)
        if "\0" in content or len(content.encode("utf-8")) > MAX_FILE_BYTES:
            raise ValueError(f"Invalid or oversized Python source: {path}")


def validate_sha(value: str) -> str:
    if not re.fullmatch(r"[a-f0-9]{40}", value):
        raise ValueError("A full, lowercase 40-character Git commit SHA is required")
    return value


def allowed_repository(settings: GitHubSettings) -> str:
    owner, repository = settings.github_owner, settings.github_repository
    if not SAFE_PART.fullmatch(owner) or not SAFE_PART.fullmatch(repository):
        raise ValueError("GitHub owner and repository must be valid repository names")
    full_name = f"{owner}/{repository}"
    if full_name.casefold() not in {name.casefold() for name in settings.github_allowed_repositories}:
        raise PermissionError("GitHub repository is outside the configured allowlist")
    return full_name
