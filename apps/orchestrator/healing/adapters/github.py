from __future__ import annotations

import html
import re
from pathlib import PurePosixPath
from typing import Any, TypedDict
from urllib.parse import quote, urlsplit

import httpx

from ..security import redact
from .base import AdapterError, GitHubSettings, allowed_repository, validate_files, validate_sha

API_VERSION = "2026-03-10"
GITHUB_API = "https://api.github.com"
DEMO_COMMIT = "local-demo"


class PullRequestResult(TypedDict):
    url: str | None
    number: int | None
    branch: str
    commit: str | None
    dry_run: bool


class GitHubHTTPError(AdapterError):
    def __init__(self, status_code: int, method: str, path: str):
        self.status_code = status_code
        super().__init__(f"GitHub {method} {path} returned HTTP {status_code}")


class GitHubAdapter:
    def __init__(self, settings: GitHubSettings, client: httpx.AsyncClient | None = None):
        self.settings = settings
        self.client = client

    async def _request(
        self,
        method: str,
        repository: str,
        path: str,
        *,
        json: dict[str, Any] | None = None,
        params: dict[str, str] | None = None,
    ) -> Any:
        headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": API_VERSION}
        if self.settings.github_token:
            headers["Authorization"] = f"Bearer {self.settings.github_token}"
        url = f"{GITHUB_API}/repos/{repository}{path}"
        try:
            if self.client is not None:
                response = await self.client.request(
                    method, url, headers=headers, json=json, params=params, follow_redirects=False
                )
            else:
                async with httpx.AsyncClient(timeout=15, follow_redirects=False) as client:
                    response = await client.request(method, url, headers=headers, json=json, params=params)
        except httpx.HTTPError:
            raise AdapterError(f"GitHub {method} {path} request failed") from None
        if not response.is_success:
            raise GitHubHTTPError(response.status_code, method, path)
        try:
            return response.json()
        except ValueError:
            raise AdapterError("GitHub returned an invalid API response") from None

    async def base_commit(self) -> str:
        if self.settings.demo_mode and self.settings.sandbox_provider == "docker":
            return DEMO_COMMIT
        repository = allowed_repository(self.settings)
        branch = quote(self.settings.github_default_branch, safe="/")
        ref = await self._request("GET", repository, f"/git/ref/heads/{branch}")
        return validate_sha(ref["object"]["sha"])

    async def create_pull_request(
        self, incident_id: str, base_sha: str, changes: dict[str, str], report: dict[str, Any], authorized: bool
    ) -> PullRequestResult:
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,80}", incident_id):
            raise ValueError("Invalid incident identifier")
        validate_files(changes)
        if not changes:
            raise ValueError("A pull request requires at least one changed source file")
        branch = f"fix/incident-{incident_id}"
        result: PullRequestResult = {"url": None, "number": None, "branch": branch, "commit": None, "dry_run": True}
        if self.settings.demo_mode or self.settings.github_dry_run:
            return result
        if authorized is not True or not self.settings.github_write_enabled:
            raise PermissionError("GitHub writes require an approved incident and enabled publication")
        if not self.settings.github_token:
            raise AdapterError("GitHub write token is required")
        validate_sha(base_sha)
        repository = allowed_repository(self.settings)
        base = self.settings.github_default_branch
        if not base or base == branch:
            raise ValueError("The incident branch must differ from the configured base branch")

        secrets = (*getattr(self.settings, "secrets", ()), self.settings.github_token)
        body = _pull_body(redact(report, secrets), sorted(changes))
        tree_sha = await self._write_tree(repository, base_sha, changes)
        commit_sha = await self._resolve_head(repository, branch, base_sha, tree_sha, incident_id)
        pull = await self._find_pull(repository, branch, base, commit_sha)
        if pull is None:
            try:
                pull = await self._request(
                    "POST", repository, "/pulls",
                    json={"title": f"Fix incident {incident_id}", "head": branch, "base": base, "body": body},
                )
            except GitHubHTTPError as error:
                if error.status_code != 422:
                    raise
                pull = await self._find_pull(repository, branch, base, commit_sha)
                if pull is None:
                    raise
        return _pull_result(pull, branch, commit_sha)

    async def _write_tree(self, repository: str, base_sha: str, changes: dict[str, str]) -> str:
        base_commit = await self._request("GET", repository, f"/git/commits/{base_sha}")
        base_tree = validate_sha(base_commit["tree"]["sha"])
        tree = await self._request("GET", repository, f"/git/trees/{base_tree}", params={"recursive": "1"})
        if tree.get("truncated"):
            raise AdapterError("GitHub base tree exceeds the validation limit")
        modes: dict[str, str] = {entry["path"]: entry["mode"] for entry in tree["tree"]}
        entries = []
        for path, content in sorted(changes.items()):
            mode = modes.get(path, "100644")
            if mode not in ("100644", "100755") or any(
                modes.get(parent.as_posix(), "040000") != "040000"
                for parent in PurePosixPath(path).parents
                if parent != PurePosixPath(".")
            ):
                raise ValueError(f"GitHub base path contains a non-regular file: {path}")
            entries.append({"path": path, "mode": mode, "type": "blob", "content": content})
        created = await self._request("POST", repository, "/git/trees", json={"base_tree": base_tree, "tree": entries})
        return validate_sha(created["sha"])

    async def _resolve_head(
        self, repository: str, branch: str, base_sha: str, tree_sha: str, incident_id: str
    ) -> str:
        existing = await self._existing_head(repository, branch, base_sha, tree_sha)
        if existing:
            return existing
        commit = await self._request(
            "POST", repository, "/git/commits",
            json={"message": f"Fix incident {incident_id}", "tree": tree_sha, "parents": [base_sha]},
        )
        commit_sha = validate_sha(commit["sha"])
        try:
            await self._request(
                "POST", repository, "/git/refs", json={"ref": f"refs/heads/{branch}", "sha": commit_sha}
            )
        except GitHubHTTPError as error:
            if error.status_code not in (409, 422):
                raise
            existing = await self._existing_head(repository, branch, base_sha, tree_sha)
            if existing is None:
                raise
            return existing
        return commit_sha

    async def _existing_head(self, repository: str, branch: str, base_sha: str, tree_sha: str) -> str | None:
        try:
            ref = await self._request("GET", repository, f"/git/ref/heads/{branch}")
        except GitHubHTTPError as error:
            if error.status_code == 404:
                return None
            raise
        sha = validate_sha(ref["object"]["sha"])
        commit = await self._request("GET", repository, f"/git/commits/{sha}")
        if commit["tree"]["sha"] != tree_sha or [parent["sha"] for parent in commit["parents"]] != [base_sha]:
            raise AdapterError("Incident branch already exists with different content")
        return sha

    async def _find_pull(
        self, repository: str, branch: str, base: str, commit_sha: str
    ) -> dict[str, Any] | None:
        owner = repository.split("/", 1)[0]
        pulls = await self._request(
            "GET", repository, "/pulls", params={"state": "all", "head": f"{owner}:{branch}", "base": base}
        )
        return next((pull for pull in pulls if pull.get("head", {}).get("sha") == commit_sha), None)


def _pull_body(report: dict[str, Any], changed_paths: list[str]) -> str:
    fields = {
        "Summary": ("summary",),
        "Cause": ("root_cause",),
        "Change": ("correction",),
        "Validation": ("validation_summary", "regression_tests"),
    }
    sections: list[str] = []

    def add(heading: str, values: list[str]) -> None:
        if values:
            escaped = html.escape("\n".join(values)).replace("@", "&#64;")
            sections.append(f"## {heading}\n\n<pre>{escaped}</pre>")

    for heading, keys in fields.items():
        values: list[str] = []
        for key in keys:
            value = report.get(key)
            if isinstance(value, str):
                values.append(value[:1000])
            if isinstance(value, list):
                values.extend(item[:300] for item in value[:5] if isinstance(item, str))
        add(heading, values)
    add("Files changed", changed_paths)
    sandbox = report.get("sandbox")
    if isinstance(sandbox, dict):
        add("Sandbox", [str(sandbox[key])[:200] for key in ("provider", "id") if sandbox.get(key)])
    commands = report.get("commands")
    if isinstance(commands, list):
        evidence = []
        for command in commands[-10:]:
            if not isinstance(command, dict) or not isinstance(command.get("command"), str):
                continue
            lines = [f"$ {command['command'][:250]}", f"Exit status {command.get('exit_code', 'unknown')}"]
            for stream in ("stdout", "stderr"):
                value = command.get(stream)
                if isinstance(value, str) and value.strip():
                    lines.append(value.strip()[-350:])
            evidence.append("\n".join(lines))
        add("Sandbox command results", ["\n\n".join(evidence)] if evidence else [])
    sections.append("## Scalingo Review App\n\nPending deployment and preview validation.")
    return "\n\n".join(sections)


def _pull_result(pull: dict[str, Any], branch: str, commit_sha: str) -> PullRequestResult:
    url, number = pull["html_url"], pull["number"]
    parsed = urlsplit(url)
    if parsed.scheme != "https" or parsed.netloc != "github.com" or type(number) is not int or number < 1:
        raise AdapterError("GitHub returned an invalid pull request URL or number")
    return {"url": url, "number": number, "branch": branch, "commit": commit_sha, "dry_run": False}
