from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class State(StrEnum):
    IDLE = "IDLE"
    INCIDENT_DETECTED = "INCIDENT_DETECTED"
    LOGS_COLLECTED = "LOGS_COLLECTED"
    DIAGNOSING = "DIAGNOSING"
    SANDBOX_CREATING = "SANDBOX_CREATING"
    REPRODUCING = "REPRODUCING"
    GENERATING_FIX = "GENERATING_FIX"
    RUNNING_TESTS = "RUNNING_TESTS"
    PR_CREATING = "PR_CREATING"
    REVIEW_APP_DEPLOYING = "REVIEW_APP_DEPLOYING"
    AWAITING_APPROVAL = "AWAITING_APPROVAL"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    RETRYING = "RETRYING"


FLOW = (
    State.IDLE, State.INCIDENT_DETECTED, State.LOGS_COLLECTED, State.DIAGNOSING,
    State.SANDBOX_CREATING, State.REPRODUCING, State.GENERATING_FIX, State.RUNNING_TESTS,
    State.PR_CREATING, State.REVIEW_APP_DEPLOYING, State.AWAITING_APPROVAL, State.COMPLETED,
)
TRANSITIONS = {state: {next_state} for state, next_state in zip(FLOW, FLOW[1:])}
TRANSITIONS[State.RUNNING_TESTS].add(State.RETRYING)
TRANSITIONS[State.RETRYING] = {State.INCIDENT_DETECTED, State.GENERATING_FIX}
TRANSITIONS[State.FAILED] = {State.RETRYING}
TRANSITIONS[State.CANCELLED] = {State.RETRYING}
TERMINAL = {State.COMPLETED, State.FAILED, State.CANCELLED}


def validate_transition(old: State, new: State) -> None:
    if old == new:
        return
    if old not in TERMINAL and new in {State.FAILED, State.CANCELLED}:
        return
    if new not in TRANSITIONS.get(old, set()):
        raise ValueError(f"Illegal transition {old} -> {new}")


class Event(BaseModel):
    id: int
    incident_id: str
    timestamp: str
    state: State
    summary: str
    tool_status: Literal["running", "success", "error", "info"]
    outputs: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None


class Incident(BaseModel):
    id: str
    state: State
    created_at: str
    updated_at: str
    attempt: int = 0
    summary: str
    error: str | None = None
    correlation_id: str
    artifacts: dict[str, Any] = Field(default_factory=dict)
    events: list[Event] = Field(default_factory=list)


class Diagnosis(BaseModel):
    model_config = ConfigDict(extra="forbid")
    summary: str
    root_cause: str
    confidence: float = Field(ge=0, le=1)


class RepairReport(Diagnosis):
    correction: str
    regression_tests: list[str]
    validation_summary: str
    files_changed: list[str]
