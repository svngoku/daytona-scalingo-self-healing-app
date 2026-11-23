import json
import os
import re
import traceback
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse

app = FastAPI(title="Pricing service")

CORRELATION_ID = re.compile(r"[A-Za-z0-9._-]{1,64}")
SECRET = re.compile(
    r"(?i)\b(?:authorization|api[-_ ]?key|password|secret|token)\b\s*[:=]\s*"
    r"""(?:"[^"]*"|'[^']*'|(?:bearer|basic)\s+[^\s,;]+|[^\s,;]+)"""
    r"|\b(?:sk-|gh[pousr]_|github_pat_|tk-us-)[A-Za-z0-9_-]{8,}"
)


def write_log(entry: dict[str, object]) -> None:
    entry["timestamp"] = datetime.now(UTC).isoformat()
    line = json.dumps(entry, separators=(",", ":"))
    print(line, flush=True)

    destination = os.getenv("LOG_PATH", ".data/broken-app.jsonl")
    if destination:
        try:
            path = Path(destination)
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as stream:
                stream.write(line + "\n")
        except OSError:
            print(
                json.dumps(
                    {
                        "timestamp": entry["timestamp"],
                        "level": "warning",
                        "event": "local_log_sink_unavailable",
                    }
                ),
                flush=True,
            )


@app.middleware("http")
async def report_request(request: Request, call_next):
    inbound_id = request.headers.get("X-Correlation-ID", "")
    correlation_id = (
        inbound_id if CORRELATION_ID.fullmatch(inbound_id) else uuid4().hex
    )
    entry: dict[str, object] = {
        "event": "request_completed",
        "level": "info",
        "correlation_id": correlation_id,
    }
    try:
        response = await call_next(request)
    except Exception as error:
        stack = "".join(traceback.format_exception(error, limit=-8))
        entry.update(
            event="quote_service_error",
            level="error",
            exception_type=type(error).__name__,
            traceback=SECRET.sub("[redacted]", stack)[-12000:],
        )
        response = JSONResponse(
            status_code=500, content={"detail": "Internal server error"}
        )

    response.headers["X-Correlation-ID"] = correlation_id
    entry["status_code"] = response.status_code
    entry["method"] = request.method
    entry["route"] = getattr(request.scope.get("route"), "path", None)
    write_log(entry)
    return response


@app.get("/")
def service() -> dict[str, str]:
    return {"service": "pricing", "health": "/health", "quote": "/api/quote?quantity=5"}


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/quote")
def quote(quantity: Annotated[int, Query(ge=0, le=1_000_000)]) -> dict[str, int | float]:
    if quantity == 0:
        raise HTTPException(status_code=400, detail="Quantity must be greater than zero")
    unit_price = 25
    discount_per_item = 10 / quantity
    return {
        "quantity": quantity,
        "unit_price": unit_price,
        "total": quantity * unit_price,
        "discount_per_item": discount_per_item,
    }
