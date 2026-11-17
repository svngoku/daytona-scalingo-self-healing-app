import asyncio
from dataclasses import asdict
from uuid import uuid4

import httpx

from .adapters.github import GitHubAdapter
from .adapters.sandbox import create_sandbox_manager
from .adapters.scalingo import ScalingoAdapter
from .agent import RepairAgent
from .demo_fixture import FixtureAgent
from .models import State, TERMINAL
from .security import redact, review_url_allowed


class Workflow:
    def __init__(self, settings, store, *, http=None, sandbox_factory=None, agent_factory=None,
                 scalingo=None, github=None):
        self.settings = settings
        self.store = store
        self.http = http or httpx.AsyncClient(timeout=15, follow_redirects=False)
        self.owns_http = http is None
        self.scalingo = scalingo or ScalingoAdapter(settings)
        self.github = github or GitHubAdapter(settings)
        self.sandbox_factory = sandbox_factory or (lambda: create_sandbox_manager(settings))
        self.agent_factory = agent_factory or (lambda: FixtureAgent() if settings.agent_mode == "fixture"
                                               else RepairAgent(settings))
        self.tasks: dict[str, asyncio.Task] = {}
        self.lock = asyncio.Lock()

    def emit(self, ident, summary, state=None, tool_status="info", outputs=None, error=None,
             artifacts=None, **kwargs):
        secrets = self.settings.secrets
        safe_artifacts = redact(artifacts or {}, secrets)
        if artifacts and "validated_changes" in artifacts:
            # Keep publication bytes identical to the code verified in the sandbox.
            safe_artifacts["validated_changes"] = artifacts["validated_changes"]
        return self.store.update(ident, summary=redact(summary, secrets), state=state, tool_status=tool_status,
                                 outputs=redact(outputs or {}, secrets), error=redact(error, secrets),
                                 artifacts=safe_artifacts, **kwargs)

    def schedule(self, ident, coroutine):
        task = asyncio.create_task(coroutine)
        self.tasks[ident] = task
        task.add_done_callback(lambda done: self.tasks.pop(ident, None) if self.tasks.get(ident) is done else None)

    async def start(self):
        async with self.lock:
            if any(not task.done() for task in self.tasks.values()):
                raise ValueError("An incident is already running; cancel it or wait for completion")
            incident = self.store.create()
            self.schedule(incident.id, self.run(incident.id))
            return incident

    async def retry(self, ident):
        async with self.lock:
            incident = self.store.get(ident)
            if incident.state not in {State.FAILED, State.CANCELLED} or ident in self.tasks:
                raise ValueError("Only stopped failed or cancelled incidents can be retried")
            if incident.attempt >= 3:
                raise ValueError("This incident has exhausted its three repair attempts")
            if incident.artifacts.get("publication_attempted"):
                raise ValueError("Inspect GitHub before retrying an incident with attempted publication")
            if any(not task.done() for task in self.tasks.values()):
                raise ValueError("Another incident is running")
            self.emit(ident, "Retry requested", State.RETRYING, reset_artifacts=True,
                      correlation_id=f"incident-{ident}-{uuid4().hex[:8]}")
            self.schedule(ident, self.run(ident))
            return self.store.get(ident)

    async def cancel(self, ident):
        async with self.lock:
            incident = self.store.get(ident)
            if incident.state in TERMINAL:
                raise ValueError("Incident already stopped")
            task = self.tasks.get(ident)
            if task:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
            if self.store.get(ident).state not in TERMINAL:
                self.emit(ident, "Cancelled by operator; existing external artifacts remain for review",
                          State.CANCELLED, artifacts={"authorization_required": False})
            return self.store.get(ident)

    async def command(self, ident, sandbox, action):
        self.emit(ident, f"Running sandbox command: {action}", tool_status="running",
                  outputs={"action": action})
        result = await sandbox.run(action)
        evidence = result.to_dict()
        for field in ("stdout", "stderr"):
            value = evidence[field]
            if len(value) > 24000:
                evidence[field] = "[earlier output truncated]\n" + value[-24000:]
        commands = self.store.get(ident).artifacts.get("commands", []) + [evidence]
        self.emit(ident, f"Sandbox {action} exited {result.exit_code}",
                  tool_status="success" if result.exit_code == 0 else "error",
                  outputs=evidence, artifacts={"commands": commands[-30:]})
        return result

    async def run(self, ident):
        sandbox = None
        agent = None
        validated = False
        try:
            incident = self.store.get(ident)
            response = await self.http.get(self.settings.broken_app_url.rstrip("/") + "/api/quote",
                                           params={"quantity": 0},
                                           headers={"X-Correlation-ID": incident.correlation_id})
            if response.status_code != 500:
                raise RuntimeError(f"Expected a real HTTP 500; staging returned {response.status_code}")
            self.emit(ident, "Staging returned HTTP 500 for the incident request", State.INCIDENT_DETECTED,
                      "success", {"status_code": 500, "correlation_id": incident.correlation_id},
                      artifacts={"simulated": self.settings.agent_mode == "fixture", "http_status": 500,
                                 "preview_validated": False, "merged": False, "production_verified": False})
            logs = await self.scalingo.fetch_recent_logs(incident.correlation_id)
            if not self.settings.demo_mode:
                for delay in (0.25, 0.5, 1, 2):
                    if logs.strip():
                        break
                    await asyncio.sleep(delay)
                    logs = await self.scalingo.fetch_recent_logs(incident.correlation_id)
            if not logs.strip():
                raise RuntimeError("No application logs were retrieved; check LOCAL_LOGS_PATH or Scalingo")
            self.emit(ident, "Application logs collected", State.LOGS_COLLECTED, "success",
                      {"logs": logs[-24000:]}, artifacts={"logs": redact(logs[-24000:], self.settings.secrets)})
            self.emit(ident, "Diagnosing the observed exception", State.DIAGNOSING, "running")
            agent = self.agent_factory()
            diagnosis = await agent.diagnose(logs)
            self.emit(ident, diagnosis.summary, tool_status="success", outputs=diagnosis.model_dump(),
                      artifacts={"diagnosis": diagnosis.model_dump()})
            base_sha = await self.github.base_commit()
            self.emit(ident, "Provisioning an isolated repair environment", State.SANDBOX_CREATING, "running")
            sandbox = self.sandbox_factory()
            async with asyncio.timeout(self.settings.sandbox_timeout_seconds):
                info = await sandbox.create(ident, base_sha)
                self.emit(ident, f"{info.provider} sandbox created", tool_status="success", outputs=asdict(info),
                          artifacts={"sandbox": asdict(info), "base_sha": base_sha})
                self.emit(ident, "Reproducing the expected behavior failure", State.REPRODUCING, "running")
                inspection = await self.command(ident, sandbox, "inspect")
                if inspection.exit_code:
                    raise RuntimeError("Could not inspect sandbox source files")
                # Snapshot original tests: model edits must not erase the evaluation oracle.
                test_paths = [line.strip() for line in inspection.stdout.splitlines()
                              if line.strip().startswith("apps/broken-app/tests/") and line.strip().endswith(".py")]
                if not test_paths:
                    raise RuntimeError("Sandbox inspection did not return the original regression test paths")
                protected = await sandbox.read_files(test_paths)
                reproduction = await self.command(ident, sandbox, "reproduce")
                evidence = reproduction.stdout + reproduction.stderr
                if (reproduction.exit_code != 1 or "test_zero_quantity_returns_400" not in evidence
                        or not any(token in evidence for token in ["AssertionError", "assert", "ZeroDivisionError"])):
                    raise RuntimeError("Reproduction did not establish the expected assertion failure")
                self.emit(ident, "Original regression fails as expected", tool_status="success",
                          artifacts={"reproduced": True})
                failures = evidence
                while self.store.get(ident).attempt < 3:
                    attempt = self.store.get(ident).attempt + 1
                    self.emit(ident, f"Repair attempt {attempt} of 3", State.GENERATING_FIX, "running", attempt=attempt)

                    async def agent_emit(summary, status, outputs):
                        self.emit(ident, summary, tool_status=status, outputs=outputs)

                    try:
                        report = await agent.repair(sandbox, {"logs": logs[-24000:], "diagnosis": diagnosis.model_dump(),
                                                   "files": inspection.stdout, "failed_tests": failures[-24000:],
                                                   "protected_tests": test_paths, "attempt": attempt}, agent_emit)
                        if await sandbox.read_files(test_paths) != protected:
                            raise ValueError("Repair modified the original regression tests")
                        self.emit(ident, "Running independent regression and service checks", State.RUNNING_TESTS,
                                  "running", artifacts={"fix_generated": True})
                        regression = await self.command(ident, sandbox, "reproduce")
                        suite = await self.command(ident, sandbox, "tests")
                        if await sandbox.read_files(test_paths) != protected:
                            raise ValueError("Sandbox tests modified the original regression tests")
                        if regression.exit_code or suite.exit_code:
                            raise ValueError("Regression or service suite failed:\n" + regression.stdout + suite.stdout
                                             + regression.stderr + suite.stderr)
                        diff = await sandbox.diff()
                        changes = await sandbox.changed_files()
                        if not diff.strip() or not changes:
                            raise ValueError("No validated code change was produced")
                        if any(secret in source for source in changes.values() for secret in self.settings.secrets):
                            raise ValueError("Validated source contains a configured credential")
                        report.validation_summary = "Regression and full pricing-service suite passed in the sandbox."
                        report.files_changed = sorted(changes)
                        self.emit(ident, "Regression and service suite passed; diff captured", tool_status="success",
                                  outputs={"files_changed": sorted(changes)},
                                  artifacts={"tests_passed": True, "diff": diff, "validated_changes": changes,
                                             "report": report.model_dump()})
                        validated = True
                        break
                    except ValueError as exc:
                        failures = str(exc)
                        await sandbox.write_files(protected)
                        if self.store.get(ident).state == State.GENERATING_FIX:
                            self.emit(ident, "Repair rejected by validation", State.RUNNING_TESTS, "error", error=failures)
                        if attempt >= 3:
                            raise RuntimeError("All three repair attempts failed: " + failures) from exc
                        self.emit(ident, "Validation failed; returning evidence to the agent", State.RETRYING,
                                  "error", error=failures)
                        inspection = await self.command(ident, sandbox, "inspect")
                        if inspection.exit_code:
                            raise RuntimeError("Could not refresh sandbox source files for the next attempt")
        except asyncio.CancelledError:
            self.emit(ident, "Execution cancelled", State.CANCELLED, artifacts={"authorization_required": False})
            raise
        except Exception as exc:
            self.emit(ident, "Incident investigation stopped", State.FAILED, "error", error=str(exc))
        finally:
            if sandbox is not None:
                try:
                    await asyncio.wait_for(sandbox.cleanup(), timeout=self.settings.command_timeout_seconds + 10)
                    info = self.store.get(ident).artifacts.get("sandbox", {})
                    self.emit(ident, "Sandbox cleaned up", artifacts={"sandbox": {**info, "status": "destroyed"}})
                except Exception as exc:
                    validated = False
                    current = self.store.get(ident)
                    state = None if current.state in TERMINAL else State.FAILED
                    self.emit(ident, "Sandbox cleanup failed; operator attention required", state,
                              "error", error=str(exc), artifacts={"cleanup_required": True})
            if agent is not None and hasattr(agent, "close"):
                try:
                    await agent.close()
                except Exception as exc:
                    self.emit(ident, "Could not close the AI client", tool_status="error", error=str(exc))
        if validated and self.store.get(ident).state == State.RUNNING_TESTS:
            self.emit(ident, "Validated patch ready for publication", State.PR_CREATING,
                      artifacts={"authorization_target": {
                          "repository": f"{self.settings.github_owner}/{self.settings.github_repository}",
                          "branch": f"fix/incident-{ident}", "base_sha": self.store.get(ident).artifacts["base_sha"]}})
            if self.settings.github_dry_run:
                await self.publish(ident, authorized=False)
            else:
                self.emit(ident, "Explicit authorization is required to create the GitHub branch and PR",
                          artifacts={"authorization_required": True})

    async def authorize(self, ident):
        async with self.lock:
            incident = self.store.get(ident)
            if (incident.state != State.PR_CREATING or not incident.artifacts.get("authorization_required")
                    or not incident.artifacts.get("tests_passed") or ident in self.tasks):
                raise ValueError("No validated patch is awaiting GitHub authorization")
            if not self.settings.github_write_enabled or self.settings.github_dry_run:
                raise ValueError("Enable GITHUB_WRITE_ENABLED and disable GITHUB_DRY_RUN in live configuration")
            self.emit(ident, "GitHub publication authorized by operator", artifacts={"authorization_required": False,
                                                                                     "authorized": True})
            self.schedule(ident, self.publish(ident, authorized=True))
            return self.store.get(ident)

    async def publish(self, ident, authorized):
        try:
            incident = self.store.get(ident)
            if not self.settings.github_dry_run:
                self.emit(ident, "Publishing validated files to a repair branch", tool_status="running",
                          artifacts={"publication_attempted": True})
            pr = await self.github.create_pull_request(
                ident, incident.artifacts["base_sha"], incident.artifacts["validated_changes"],
                {**incident.artifacts["report"], "commands": incident.artifacts.get("commands", []),
                 "sandbox": incident.artifacts.get("sandbox")},
                authorized=authorized)
            self.emit(ident, "Dry-run: patch ready; no GitHub writes or Review App" if pr.get("dry_run")
                      else "GitHub pull request opened", tool_status="success", outputs=pr,
                      artifacts={"pr": pr, "publication_status": "dry_run" if pr.get("dry_run") else "published",
                                 "authorization_required": False})
            if pr.get("dry_run"):
                return
            self.emit(ident, "Waiting for the associated Scalingo Review App", State.REVIEW_APP_DEPLOYING, "running")
            async with asyncio.timeout(self.settings.review_timeout_seconds):
                while True:
                    review = await self.scalingo.get_review_app_status(pr["number"])
                    self.emit(ident, f"Review App deployment: {review['status']}", outputs=review,
                              artifacts={"review_app": review})
                    if review["status"] == "failed":
                        raise RuntimeError("Scalingo Review App deployment failed")
                    if review["status"] == "ready" and review.get("url"):
                        await self.smoke(review["url"])
                        self.emit(ident, "Preview validated. Human GitHub review and merge are required.",
                                  State.AWAITING_APPROVAL, "success", artifacts={"preview_validated": True})
                        return
                    await asyncio.sleep(self.settings.review_poll_seconds)
        except asyncio.CancelledError:
            self.emit(ident, "Publication monitoring cancelled; inspect external artifacts before retrying", State.CANCELLED)
            raise
        except Exception as exc:
            self.emit(ident, "Publication or preview validation stopped", State.FAILED, "error", error=str(exc))

    async def smoke(self, url):
        if not review_url_allowed(url, self.settings.review_allowed_hosts):
            raise RuntimeError("Review App URL is not an allowed HTTPS Scalingo host")
        for path, expected in [("/health", 200), ("/api/quote?quantity=5", 200), ("/api/quote?quantity=0", 400)]:
            response = await self.http.get(url.rstrip("/") + path)
            if response.status_code != expected:
                raise RuntimeError(f"Preview smoke check {path}: expected {expected}, got {response.status_code}")
            payload = response.json()
            if expected == 400:
                detail = payload.get("detail") if isinstance(payload, dict) else None
                if not isinstance(detail, str) or "quantity" not in detail.casefold():
                    raise RuntimeError("Preview rejected zero quantity without a meaningful validation error")

    def recover(self):
        for incident in self.store.list():
            if incident.state in TERMINAL | {State.AWAITING_APPROVAL}:
                continue
            if incident.state == State.PR_CREATING and (
                incident.artifacts.get("authorization_required") or incident.artifacts.get("publication_status") == "dry_run"
            ):
                continue
            self.emit(incident.id, "Orchestrator restarted; interrupted work requires explicit retry",
                      State.FAILED, "error", error="Process interrupted; verify sandbox cleanup before retrying")

    async def close(self):
        tasks = list(self.tasks.values())
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        for adapter in (self.scalingo, self.github):
            if hasattr(adapter, "close"):
                await adapter.close()
        if self.owns_http:
            await self.http.aclose()
