import asyncio
import hmac
import json
from contextlib import asynccontextmanager

from fastapi import APIRouter, Depends, FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict

from .config import Settings
from .security import redact
from .store import Store
from .workflow import Workflow


class Authorization(BaseModel):
    model_config = ConfigDict(extra="forbid")
    authorized: bool


def create_app(settings=None, store=None, workflow=None):
    settings = settings or Settings()
    store = store or Store(settings.database_path)
    workflow = workflow or Workflow(settings, store)

    @asynccontextmanager
    async def lifespan(app):
        workflow.recover()
        yield
        await workflow.close()
        store.close()

    app = FastAPI(title="Self-Healing App — Daytona × Scalingo", lifespan=lifespan)
    app.state.store, app.state.workflow, app.state.settings = store, workflow, settings
    app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins, allow_methods=["GET", "POST"],
                       allow_headers=["Content-Type", "X-Orchestrator-Token", "Last-Event-ID"])

    async def authenticate(x_orchestrator_token: str = Header(default="")):
        if settings.orchestrator_api_token and not hmac.compare_digest(
            settings.orchestrator_api_token.encode("utf-8"), x_orchestrator_token.encode("utf-8")
        ):
            raise HTTPException(401, "A valid X-Orchestrator-Token is required")

    router = APIRouter(prefix="/api", dependencies=[Depends(authenticate)])

    def public(incident):
        return redact(incident.model_dump(mode="json"), settings.secrets)

    def get(ident):
        try:
            return store.get(ident)
        except KeyError:
            raise HTTPException(404, "Incident not found") from None

    async def action(operation, ident=None):
        if ident is not None:
            get(ident)
        try:
            return public(await operation())
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    @router.get("/status")
    async def status():
        staging = {"url": settings.broken_app_url, "healthy": False, "status_code": None}
        try:
            response = await workflow.http.get(settings.broken_app_url.rstrip("/") + "/health")
            staging.update(healthy=response.status_code == 200, status_code=response.status_code)
        except Exception:
            pass
        providers = {
            "daytona": {"status": "local" if settings.sandbox_provider == "docker" else
                         "configured" if settings.daytona_api_key else "missing",
                         "detail": "Docker isolation" if settings.sandbox_provider == "docker" else
                         "Credential configured; live access not yet verified"},
            "scalingo": {"status": "local" if settings.demo_mode else
                          "configured" if settings.scalingo_api_token and settings.scalingo_app_name else "missing",
                          "detail": "Local FastAPI and actual file logs" if settings.demo_mode else
                          "Scalingo logs and PR Review Apps"},
            "github": {"status": "dry_run" if settings.github_dry_run else "configured" if settings.github_token else "missing",
                        "detail": "Publication disabled" if settings.github_dry_run else "Explicit per-incident authorization required"},
            "openrouter": {
                "status": "simulated" if settings.agent_mode == "fixture" else
                          "configured" if settings.openrouter_api_key.strip() else "missing",
                "detail": "Scripted fixture; no AI request" if settings.agent_mode == "fixture"
                          else settings.openrouter_model,
            },
        }
        return redact(
            {"mode": "local" if settings.demo_mode else "live", "agent_mode": settings.agent_mode,
             "providers": providers, "staging": staging, "github_write_enabled": settings.github_write_enabled,
             "github_dry_run": settings.github_dry_run},
            settings.secrets,
        )

    @router.post("/incidents", status_code=202)
    async def start():
        return await action(workflow.start)

    @router.get("/incidents")
    async def incidents():
        return [public(incident) for incident in store.list()]

    @router.get("/incidents/{ident}")
    async def detail(ident: str):
        return public(get(ident))

    @router.post("/incidents/{ident}/retry", status_code=202)
    async def retry(ident: str):
        return await action(lambda: workflow.retry(ident), ident)

    @router.post("/incidents/{ident}/cancel")
    async def cancel(ident: str):
        return await action(lambda: workflow.cancel(ident), ident)

    @router.post("/incidents/{ident}/authorize", status_code=202)
    async def authorize(ident: str, body: Authorization):
        if not body.authorized:
            raise HTTPException(400, "Explicit authorization was not granted")
        return await action(lambda: workflow.authorize(ident), ident)

    @router.get("/incidents/{ident}/events")
    async def events(ident: str, request: Request, last_event_id: str = Header(default="0")):
        get(ident)
        try:
            cursor = max(0, int(last_event_id))
        except ValueError:
            raise HTTPException(400, "Last-Event-ID must be an integer") from None

        async def stream():
            nonlocal cursor
            idle = 0
            while not await request.is_disconnected():
                batch = store.events(ident, cursor)
                for event in batch:
                    cursor = event.id
                    data = json.dumps(redact(event.model_dump(mode="json"), settings.secrets))
                    yield f"id: {cursor}\nevent: workflow\ndata: {data}\n\n"
                idle += 1
                if idle % 50 == 0:
                    yield ": heartbeat\n\n"
                await asyncio.sleep(0.2)

        return StreamingResponse(stream(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    app.include_router(router)
    return app


app = create_app()
