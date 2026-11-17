from __future__ import annotations

import asyncio
import re
from contextlib import asynccontextmanager
from time import monotonic
from typing import Any, AsyncIterator
from urllib.parse import urlsplit

import httpx

from .base import AdapterError, ScalingoSettings

AUTH_URL = "https://auth.scalingo.com/v1/tokens/exchange"
MAX_LOG_BYTES = 65_536
LOG_LINES = 200


class ScalingoAdapter:
    def __init__(self, settings: ScalingoSettings, client: httpx.AsyncClient | None = None):
        self.settings = settings
        self.client = client
        self._token: str | None = None
        self._token_expiration = 0.0
        self._token_lock = asyncio.Lock()

    @asynccontextmanager
    async def _client(self) -> AsyncIterator[httpx.AsyncClient]:
        if self.client is not None:
            yield self.client
        else:
            async with httpx.AsyncClient(timeout=15, follow_redirects=False) as client:
                yield client

    async def _bearer(self, client: httpx.AsyncClient) -> str:
        async with self._token_lock:
            if self._token and monotonic() < self._token_expiration:
                return self._token
            if not self.settings.scalingo_api_token:
                raise AdapterError("Scalingo API token is required")
            try:
                response = await client.post(
                    AUTH_URL,
                    auth=httpx.BasicAuth("", self.settings.scalingo_api_token),
                    headers={"Accept": "application/json"},
                    follow_redirects=False,
                )
                response.raise_for_status()
                token = response.json()["token"]
                if not isinstance(token, str) or not token:
                    raise ValueError("Missing bearer token")
            except (httpx.HTTPError, ValueError, KeyError, TypeError):
                raise AdapterError("Scalingo token exchange failed") from None
            self._token = token
            self._token_expiration = monotonic() + 3_300
            return self._token

    def _app_path(self, app_name: str | None = None) -> str:
        name = app_name if app_name is not None else self.settings.scalingo_app_name
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,127}", name):
            raise ValueError("Invalid Scalingo application name")
        return f"/apps/{name}"

    def _api_url(self) -> str:
        base = self.settings.scalingo_api_url.rstrip("/")
        uri = urlsplit(base)
        if (
            uri.scheme != "https"
            or not re.fullmatch(r"api\.[a-z0-9-]+\.scalingo\.com", uri.hostname or "")
            or uri.netloc != uri.hostname
            or uri.path not in ("", "/v1")
            or uri.query
            or uri.fragment
        ):
            raise ValueError("Scalingo API URL must be a regional HTTPS Scalingo endpoint")
        return base if uri.path else f"{base}/v1"

    async def _get(
        self, path: str, *, params: dict[str, str] | None = None, allow_missing: bool = False
    ) -> dict[str, Any] | None:
        url = f"{self._api_url()}{path}"
        async with self._client() as client:
            for attempt in range(2):
                token = await self._bearer(client)
                try:
                    response = await client.get(
                        url,
                        params=params,
                        headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
                        follow_redirects=False,
                    )
                except httpx.HTTPError:
                    raise AdapterError("Scalingo API request failed") from None
                if response.status_code == 401 and attempt == 0:
                    async with self._token_lock:
                        if self._token == token:
                            self._token = None
                    continue
                if response.status_code == 404 and allow_missing:
                    return None
                if not response.is_success:
                    raise AdapterError(f"Scalingo API returned HTTP {response.status_code} for {path}")
                try:
                    payload = response.json()
                    if isinstance(payload, dict):
                        return payload
                except ValueError:
                    pass
                raise AdapterError("Scalingo API returned an invalid response")
        raise AdapterError("Scalingo authorization failed")

    async def get_application(self) -> dict[str, Any]:
        if self.settings.demo_mode:
            return {"name": self.settings.scalingo_app_name, "url": self.settings.broken_app_url}
        return await self._get_application(self._app_path())

    async def _get_application(self, path: str) -> dict[str, Any]:
        response = await self._get(path)
        app = (response or {}).get("app")
        if not isinstance(app, dict):
            raise AdapterError("Scalingo did not return application metadata")
        return app

    async def fetch_recent_logs(self, correlation_id: str | None = None) -> str:
        if self.settings.demo_mode:
            lines = await asyncio.to_thread(self._local_logs)
        else:
            response = await self._get(f"{self._app_path()}/logs")
            logs_url = (response or {}).get("logs_url")
            if not isinstance(logs_url, str):
                raise AdapterError("Scalingo did not return an application logs URL")
            lines = await self._download_logs(logs_url)
        # Preserve unkeyed traceback lines around a correlated runtime log entry.
        indexes = range(len(lines))
        if correlation_id:
            correlated = {
                neighbor
                for index in indexes
                if correlation_id in lines[index]
                for neighbor in range(max(0, index - 2), min(len(lines), index + 21))
            }
            indexes = sorted(correlated)
        return "\n".join(lines[index] for index in indexes)

    def _local_logs(self) -> list[str]:
        try:
            with self.settings.local_logs_path.open("rb") as log:
                size = log.seek(0, 2)
                log.seek(max(0, size - MAX_LOG_BYTES))
                return log.read(MAX_LOG_BYTES).decode("utf-8", errors="replace").splitlines()[-LOG_LINES:]
        except FileNotFoundError:
            return []

    async def _download_logs(self, logs_url: str) -> list[str]:
        url = httpx.URL(logs_url)
        if (
            url.scheme != "https"
            or not url.host.endswith(".scalingo.com")
            or not url.host.startswith("logs.")
            or url.userinfo
            or url.port is not None
        ):
            raise AdapterError("Scalingo returned an unexpected application logs URL")
        url = url.copy_merge_params({"n": LOG_LINES, "stream": "false"})
        try:
            async with self._client() as client:
                # Strip any default authentication and bearer headers on an injected client.
                request = httpx.Request("GET", url, headers={"Accept": "text/plain"})
                response = await client.send(request, stream=True, auth=None, follow_redirects=False)
                try:
                    response.raise_for_status()
                    body = bytearray()
                    async for chunk in response.aiter_bytes(chunk_size=8_192):
                        body.extend(chunk)
                        if len(body) > MAX_LOG_BYTES:
                            del body[:-MAX_LOG_BYTES]
                finally:
                    await response.aclose()
        except httpx.HTTPError:
            raise AdapterError("Scalingo application log download failed") from None
        return bytes(body).decode("utf-8", errors="replace").splitlines()[-LOG_LINES:]

    async def get_deployment_status(self, app_name: str | None = None) -> dict[str, Any]:
        if self.settings.demo_mode:
            return {"status": "local", "app_name": app_name or self.settings.scalingo_app_name}
        response = await self._get(f"{self._app_path(app_name)}/deployments", params={"per_page": "1"})
        deployments = (response or {}).get("deployments", [])
        return deployments[0] if deployments else {"status": "pending", "app_name": app_name}

    async def get_review_app_status(self, pr_number: int) -> dict[str, str | None]:
        if pr_number < 1:
            raise ValueError("Pull request number must be positive")
        empty: dict[str, str | None] = {"status": "unavailable", "app_name": None, "url": None}
        if self.settings.demo_mode:
            return empty
        response = await self._get(f"{self._app_path()}/scm_repo_link/review_apps", allow_missing=True)
        if response is None:
            return empty
        for app in response.get("review_apps", []):
            if (app.get("pull_request") or {}).get("number") != pr_number:
                continue
            app_name = app.get("app_name")
            if not isinstance(app_name, str) or not app_name:
                break
            status = (app.get("last_deployment") or {}).get("status")
            if status == "success":
                metadata = await self._get_application(self._app_path(app_name))
                url = metadata.get("url") or metadata.get("base_url")
                if isinstance(url, str):
                    parsed = urlsplit(url)
                    if parsed.scheme == "https" and parsed.hostname and parsed.username is None:
                        return {"status": "ready", "app_name": app_name, "url": url}
            if status in {"build-error", "crashed", "aborted", "failed", "error", "canceled", "cancelled"}:
                return {"status": "failed", "app_name": app_name, "url": None}
            return {"status": "pending", "app_name": app_name, "url": None}
        return {"status": "pending", "app_name": None, "url": None}

    async def get_review_app_url(self, pr_number: int) -> str | None:
        return (await self.get_review_app_status(pr_number))["url"]
