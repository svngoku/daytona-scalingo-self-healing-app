from __future__ import annotations

import asyncio
import base64
import math
import os
import shlex
import stat
import tarfile
from abc import ABC, abstractmethod
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import TYPE_CHECKING, BinaryIO, Sequence
from uuid import uuid4

from .base import (
    APP_PATH,
    MAX_FILE_BYTES,
    MAX_FILES,
    OUTPUT_LIMIT,
    OUTPUT_TRUNCATED,
    AdapterError,
    CommandResult,
    SandboxInfo,
    SandboxSettings,
    allowed_repository,
    validate_files,
    validate_python_path,
    validate_sha,
)

if TYPE_CHECKING:
    from daytona import Daytona, Sandbox

WORKDIR = "/tmp/healing-repo"
VENV = "/tmp/healing-venv"
GIT = ("git", "-c", "core.hooksPath=/dev/null", "--no-pager")
PYTEST = (
    "env", "PYTHONDONTWRITEBYTECODE=1", "PYTEST_DISABLE_PLUGIN_AUTOLOAD=1",
    f"{VENV}/bin/python", "-m", "pytest", "-q", "-p", "no:cacheprovider",
    f"{APP_PATH}/tests",
)
ACTIONS = {
    "inspect": ("find", APP_PATH, "-type", "f", "-name", "*.py"),
    "reproduce": (*PYTEST, "-k", "test_zero_quantity_returns_400"),
    "tests": PYTEST,
}
SOURCE_IO = """
import base64
from pathlib import Path
import stat
import sys

operation, name, *arguments = sys.argv[1:]
path = Path(name)
for parent in reversed(path.parents):
    if parent.is_symlink():
        raise ValueError("Symlink in source path")
if path.is_symlink():
    raise ValueError("Symlink in source path")
if path.exists() and not stat.S_ISREG(path.stat().st_mode):
    raise ValueError("Expected a regular file")
if operation == "read":
    with path.open("rb") as source:
        data = source.read(int(arguments[0]) + 1)
    if len(data) > int(arguments[0]):
        raise ValueError("Source exceeds size limit")
    print(base64.b64encode(data).decode("ascii"))
else:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(base64.b64decode(arguments[0], validate=True))
"""


class SandboxManager(ABC):
    def __init__(self, settings: SandboxSettings):
        if settings.command_timeout_seconds < 1 or settings.sandbox_timeout_seconds < 1:
            raise ValueError("Sandbox and command timeouts must be positive")
        self.settings = settings

    @abstractmethod
    async def create(self, incident_id: str, base_commit: str) -> SandboxInfo:
        ...

    @abstractmethod
    async def cleanup(self) -> None:
        ...

    @abstractmethod
    async def _exec(
        self, command: Sequence[str], *, cwd: str = WORKDIR, timeout: int | None = None
    ) -> CommandResult:
        ...

    async def _require(
        self,
        label: str,
        command: Sequence[str],
        *,
        cwd: str = WORKDIR,
        timeout: int | None = None,
    ) -> str:
        result = await self._exec(command, cwd=cwd, timeout=timeout)
        if result.exit_code or result.stdout.endswith(OUTPUT_TRUNCATED):
            raise AdapterError(f"Sandbox could not {label} (exit {result.exit_code})")
        return result.stdout

    async def _get_checkout(self, base_commit: str, repository: str) -> None:
        await self._require("initialize checkout", (*GIT, "init", WORKDIR), cwd="/tmp")
        await self._require(
            "fetch the public GitHub commit",
            (
                "env", "GIT_TERMINAL_PROMPT=0", *GIT, "fetch", "--depth=1", "--no-tags",
                f"https://github.com/{repository}.git", base_commit,
            ),
            timeout=self.settings.sandbox_timeout_seconds,
        )
        await self._require("check out the base commit", (*GIT, "checkout", "--detach", "FETCH_HEAD"))
        revision = await self._require("read the checked-out SHA", (*GIT, "rev-parse", "HEAD"))
        if revision.strip() != base_commit:
            raise AdapterError("Sandbox checked out a different base commit")

    async def _install_dependencies(self) -> None:
        timeout = self.settings.sandbox_timeout_seconds
        await self._require("create a Python environment", ("python3", "-m", "venv", VENV), timeout=timeout)
        await self._require(
            "install baseline dependencies",
            (
                f"{VENV}/bin/python", "-m", "pip", "--isolated", "install",
                "--disable-pip-version-check", "--no-input", "--no-cache-dir",
                "--only-binary=:all:", "-r", f"{APP_PATH}/requirements.txt", "pytest==8.4.2", "httpx==0.28.1",
            ),
            timeout=timeout,
        )

    async def run(self, action: str) -> CommandResult:
        if action not in ACTIONS:
            raise ValueError("Sandbox action must be inspect, reproduce, or tests")
        result = await self._exec(ACTIONS[action])
        if action != "inspect" or result.exit_code:
            return result
        if result.stdout.endswith(OUTPUT_TRUNCATED):
            raise AdapterError("Sandbox source listing exceeds output limit")
        paths = [path for path in result.stdout.splitlines() if "/__pycache__/" not in path]
        for path in paths:
            validate_python_path(path)
        return CommandResult(result.command, "\n".join(sorted(paths)), result.stderr, result.exit_code)

    async def read_files(self, paths: list[str]) -> dict[str, str]:
        if len(paths) > MAX_FILES * 4:
            raise ValueError("Too many requested Python source files")
        for path in paths:
            validate_python_path(path)
        result: dict[str, str] = {}
        for path in paths:
            encoded = await self._require(
                f"read {path}", ("python3", "-I", "-S", "-c", SOURCE_IO, "read", path, str(MAX_FILE_BYTES))
            )
            result[path] = base64.b64decode(encoded.strip(), validate=True).decode("utf-8")
        return result

    async def write_files(self, files: dict[str, str]) -> None:
        validate_files(files)
        for path, source in files.items():
            encoded = base64.b64encode(source.encode("utf-8")).decode("ascii")
            await self._require(
                f"write {path}", ("python3", "-I", "-S", "-c", SOURCE_IO, "write", path, encoded)
            )

    async def _changes(self) -> list[tuple[str, bool]]:
        status = await self._require(
            "inspect the Git worktree",
            (*GIT, "status", "--porcelain=v1", "-z", "--no-renames", "--untracked-files=all"),
        )
        changes: list[tuple[str, bool]] = []
        for entry in status.split("\0"):
            if not entry:
                continue
            mode, separator, path = entry[0:2], entry[2:3], entry[3:]
            if separator != " " or mode not in {" M", "??"}:
                raise AdapterError("Sandbox contains an unexpected staged change, deletion, or file type change")
            validate_python_path(path)
            changes.append((path, mode == "??"))
        if len(changes) > MAX_FILES:
            raise AdapterError("Sandbox changed too many files")
        return changes

    async def changed_files(self) -> dict[str, str]:
        changes = await self._changes()
        files = await self.read_files([path for path, _ in changes])
        validate_files(files)
        return files

    async def diff(self) -> str:
        changes = await self._changes()
        if not changes:
            return ""
        validate_files(await self.read_files([path for path, _ in changes]))
        tracked = [path for path, is_new in changes if not is_new]
        git_diff = (*GIT, "diff", "--no-ext-diff", "--no-textconv", "--no-color")
        parts = []
        if tracked:
            parts.append(await self._require("read tracked diff", (*git_diff, "HEAD", "--", *tracked)))
        for path, is_new in changes:
            if is_new:
                result = await self._exec((*git_diff, "--no-index", "--", "/dev/null", path))
                if result.exit_code != 1 or result.stdout.endswith(OUTPUT_TRUNCATED):
                    raise AdapterError("Sandbox could not read new file diff")
                parts.append(result.stdout)
        return "".join(parts)


async def _read_bounded(stream: asyncio.StreamReader) -> str:
    output = bytearray()
    truncated = False
    while chunk := await stream.read(8192):
        remaining = OUTPUT_LIMIT - len(output)
        output.extend(chunk[:remaining])
        if len(chunk) > remaining:
            truncated = True
    result = output.decode("utf-8", errors="replace")
    return result + OUTPUT_TRUNCATED if truncated else result


def _copy_demo_source(repo: Path, staging: Path) -> None:
    source = repo / APP_PATH
    if source.is_symlink() or source.parent.is_symlink() or not source.is_dir():
        raise AdapterError("The local broken application source directory is unavailable")
    total = 0
    for directory, dirs, names in os.walk(source, followlinks=False):
        directory_path = Path(directory)
        dirs[:] = [
            name for name in dirs
            if not name.startswith(".") and name != "__pycache__" and not (directory_path / name).is_symlink()
        ]
        for name in names:
            path = directory_path / name
            if not stat.S_ISREG(path.lstat().st_mode):
                continue
            relative = path.relative_to(repo).as_posix()
            if relative != f"{APP_PATH}/requirements.txt":
                if not name.endswith(".py"):
                    continue
                validate_python_path(relative)
            with path.open("rb") as handle:
                content = handle.read(MAX_FILE_BYTES + 1)
            total += len(content)
            if len(content) > MAX_FILE_BYTES or total > 1_048_576:
                raise AdapterError("Local sandbox source exceeds the copy limit")
            destination = staging / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(content)


def _package_demo_source(repo: Path, temporary: Path) -> Path:
    def root_owned(member: tarfile.TarInfo) -> tarfile.TarInfo:
        member.uid = member.gid = 0
        member.uname = member.gname = "root"
        member.mode = 0o755 if member.isdir() else 0o644
        return member

    staging = temporary / "source"
    _copy_demo_source(repo, staging)
    archive_path = temporary / "source.tar"
    with tarfile.open(archive_path, mode="w") as archive:
        archive.add(staging / "apps", arcname="apps", filter=root_owned)
    return archive_path


class DockerSandboxManager(SandboxManager):
    def __init__(self, settings: SandboxSettings):
        super().__init__(settings)
        self.docker_binary: str = getattr(settings, "docker_binary", "docker")
        self._name: str | None = None

    async def _docker(
        self, *args: str, timeout: int | None = None, stdin: BinaryIO | None = None
    ) -> CommandResult:
        argv = (self.docker_binary, *args)
        try:
            process = await asyncio.create_subprocess_exec(
                *argv, stdin=stdin, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )
        except FileNotFoundError:
            raise AdapterError("Docker executable is unavailable") from None
        assert process.stdout is not None and process.stderr is not None
        readers = asyncio.gather(_read_bounded(process.stdout), _read_bounded(process.stderr))
        try:
            stdout, stderr = await asyncio.wait_for(
                asyncio.shield(readers), timeout=timeout or self.settings.command_timeout_seconds
            )
            await process.wait()
        except (TimeoutError, asyncio.CancelledError) as error:
            if process.returncode is None:
                try:
                    process.kill()
                except ProcessLookupError:
                    pass
            await readers
            await process.wait()
            if isinstance(error, asyncio.CancelledError):
                raise
            return CommandResult(shlex.join(argv[:2]), "", "Docker operation timed out", 124)
        assert process.returncode is not None
        return CommandResult(shlex.join(argv[:2]), stdout, stderr, process.returncode)

    async def create(self, incident_id: str, base_commit: str) -> SandboxInfo:
        if self._name is not None:
            raise AdapterError("This sandbox manager already has a container")
        if not self.settings.demo_mode:
            validate_sha(base_commit)
            repository = allowed_repository(self.settings)
        image = self.settings.sandbox_image
        if not image or image.startswith("-"):
            raise ValueError("Invalid sandbox image")
        self._name = f"healing-{uuid4().hex}"
        result = await self._docker(
            "run", "--detach", "--name", self._name, "--network", "bridge",
            "--memory", "512m", "--cpus", "1", "--pids-limit", "96", "--cap-drop", "ALL",
            "--security-opt", "no-new-privileges", "--log-driver", "none",
            image, "sleep", str(max(600, self.settings.sandbox_timeout_seconds * 5)),
            timeout=self.settings.sandbox_timeout_seconds,
        )
        if result.exit_code:
            raise AdapterError(f"Could not create Docker sandbox: {result.stderr[:300]}")
        sandbox_id = result.stdout.strip()
        if self.settings.demo_mode:
            await self._require("make a worktree directory", ("mkdir", "-p", WORKDIR), cwd="/tmp")
            with TemporaryDirectory(prefix="healing-source-") as temporary:
                archive_path = await asyncio.to_thread(_package_demo_source, self.settings.repo_root, Path(temporary))
                # A streamed archive preserves normalized UIDs across Docker hosts.
                with archive_path.open("rb") as archive:
                    copied = await self._docker("cp", "-", f"{self._name}:{WORKDIR}", stdin=archive)
                if copied.exit_code:
                    raise AdapterError("Could not copy demo application source into Docker")
            await self._require("initialize Git baseline", (*GIT, "init"))
            await self._require("stage baseline source", (*GIT, "add", "-f", "--", APP_PATH))
            await self._require(
                "save baseline source",
                (*GIT, "-c", "user.name=Healing", "-c", "user.email=healing@localhost",
                 "commit", "-qm", "Capture local demo baseline"),
            )
        else:
            await self._get_checkout(base_commit, repository)
        await self._install_dependencies()
        disconnected = await self._docker("network", "disconnect", "bridge", self._name)
        if disconnected.exit_code:
            raise AdapterError("Could not disconnect Docker sandbox network")
        return SandboxInfo(sandbox_id, "docker", "ready")

    async def _exec(
        self, command: Sequence[str], *, cwd: str = WORKDIR, timeout: int | None = None
    ) -> CommandResult:
        if self._name is None:
            raise AdapterError("Docker sandbox is unavailable")
        deadline = timeout or self.settings.command_timeout_seconds
        result = await self._docker(
            "exec", "--workdir", cwd, self._name, "timeout", "--kill-after=2s", f"{deadline}s",
            *command, timeout=deadline + 5,
        )
        return CommandResult(shlex.join(command), result.stdout, result.stderr, result.exit_code)

    async def cleanup(self) -> None:
        if self._name is None:
            return
        result = await self._docker("rm", "--force", self._name)
        if result.exit_code and "No such container" not in result.stderr:
            raise AdapterError("Could not clean up Docker sandbox")
        self._name = None


class DaytonaSandboxManager(SandboxManager):
    def __init__(self, settings: SandboxSettings):
        super().__init__(settings)
        self._client: Daytona | None = None
        self._sandbox: Sandbox | None = None

    def _create(self) -> str:
        from daytona import CreateSandboxFromImageParams, Daytona, DaytonaConfig, Resources

        self._client = Daytona(DaytonaConfig(
            api_key=self.settings.daytona_api_key, api_url=self.settings.daytona_api_url,
            connection_pool_maxsize=4,
        ))
        self._sandbox = self._client.create(
            CreateSandboxFromImageParams(
                image=self.settings.sandbox_image,
                language="python",
                resources=Resources(cpu=1, memory=2, disk=5),
                auto_stop_interval=5,
                ephemeral=True,
                ttl_minutes=max(10, math.ceil(self.settings.sandbox_timeout_seconds * 5 / 60)),
                public=False,
            ),
            timeout=self.settings.sandbox_timeout_seconds,
        )
        return self._sandbox.id

    async def create(self, incident_id: str, base_commit: str) -> SandboxInfo:
        if self._client is not None:
            raise AdapterError("This sandbox manager already has a Daytona client")
        if not self.settings.daytona_api_key:
            raise AdapterError("Daytona API key is required")
        validate_sha(base_commit)
        repository = allowed_repository(self.settings)
        # Finish the in-flight provisioning request on cancellation so cleanup can find it.
        creation = asyncio.create_task(asyncio.to_thread(self._create))
        try:
            sandbox_id = await asyncio.shield(creation)
        except asyncio.CancelledError:
            await asyncio.gather(creation, return_exceptions=True)
            raise
        except Exception:
            raise AdapterError("Could not create Daytona sandbox") from None
        await self._get_checkout(base_commit, repository)
        await self._install_dependencies()
        assert self._sandbox is not None
        try:
            await asyncio.to_thread(
                self._sandbox.update_network_settings,
                network_block_all=True,
                request_timeout=self.settings.command_timeout_seconds,
            )
        except Exception:
            raise AdapterError("Could not block Daytona sandbox outbound network") from None
        return SandboxInfo(sandbox_id, "daytona", "ready")

    async def _exec(
        self, command: Sequence[str], *, cwd: str = WORKDIR, timeout: int | None = None
    ) -> CommandResult:
        if self._sandbox is None:
            raise AdapterError("Daytona sandbox is unavailable")
        quoted = shlex.join(command)
        # Byte-limit the response before transfer and retain the program's exit status.
        script = (
            f"{quoted} 2>&1 | "
            f"{{ head -c {OUTPUT_LIMIT + 1}; cat >/dev/null; }}"
        )
        deadline = timeout or self.settings.command_timeout_seconds
        wrapped = shlex.join(
            ("timeout", "--kill-after=2s", f"{deadline}s", "bash", "-o", "pipefail", "-c", script)
        )
        try:
            result = await asyncio.to_thread(
                self._sandbox.process.exec, wrapped, cwd=cwd, timeout=deadline + 5
            )
        except Exception:
            raise AdapterError("Daytona command execution failed") from None
        output = result.result.encode("utf-8")
        text = output[:OUTPUT_LIMIT].decode("utf-8", errors="replace")
        if len(output) > OUTPUT_LIMIT:
            text += OUTPUT_TRUNCATED
        return CommandResult(quoted, text, "", result.exit_code)

    async def cleanup(self) -> None:
        if self._client is None:
            return
        client = self._client
        try:
            if self._sandbox is not None:
                await asyncio.to_thread(
                    client.delete, self._sandbox, timeout=self.settings.command_timeout_seconds, wait=True
                )
        except Exception:
            raise AdapterError("Could not confirm Daytona sandbox cleanup") from None
        finally:
            # The stable sync SDK finalizes its shared HTTP pool when these references are released.
            self._sandbox = None
            self._client = None


def create_sandbox_manager(settings: SandboxSettings) -> SandboxManager:
    if settings.sandbox_provider == "docker":
        return DockerSandboxManager(settings)
    if settings.sandbox_provider == "daytona":
        return DaytonaSandboxManager(settings)
    raise ValueError("Sandbox provider must be docker or daytona")
