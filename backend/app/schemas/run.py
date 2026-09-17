from datetime import datetime
from typing import Optional
from pydantic import BaseModel, field_validator


# ---------------------------------------------------------------------------
# Request schemas
# ---------------------------------------------------------------------------

class RunCreate(BaseModel):
    """Payload accepted for POST /api/runs.

    Only agent_id, task_id, status, execution_time_ms, and error_message are accepted.
    user_id is never accepted from the client; it is derived through agent ownership.
    """

    agent_id: int
    task_id: Optional[int] = None
    status: Optional[str] = None
    execution_time_ms: Optional[int] = None
    error_message: Optional[str] = None

    @field_validator("agent_id")
    @classmethod
    def agent_id_positive(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("agent_id must be a positive integer.")
        return v

    @field_validator("task_id")
    @classmethod
    def task_id_non_negative(cls, v: Optional[int]) -> Optional[int]:
        # task_id can be NULL (standalone run) or a positive int referencing a task
        if v is not None and v <= 0:
            raise ValueError("task_id must be a positive integer or NULL.")
        return v

    @field_validator("status")
    @classmethod
    def status_valid(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        v = v.strip().lower()
        valid = {"running", "completed", "failed", "cancelled"}
        if v not in valid:
            raise ValueError(f"status must be one of {valid}.")
        return v

    @field_validator("execution_time_ms")
    @classmethod
    def execution_time_non_negative(cls, v: Optional[int]) -> Optional[int]:
        if v is not None and v < 0:
            raise ValueError("execution_time_ms must be non-negative.")
        return v


class RunUpdate(BaseModel):
    """Payload accepted for PATCH /api/runs/{run_id} — partial update.

    Only status, execution_time_ms, and error_message can be updated.
    agent_id and task_id cannot be changed after creation.
    """

    status: Optional[str] = None
    execution_time_ms: Optional[int] = None
    error_message: Optional[str] = None

    @field_validator("status")
    @classmethod
    def status_valid(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        v = v.strip().lower()
        valid = {"running", "completed", "failed", "cancelled"}
        if v not in valid:
            raise ValueError(f"status must be one of {valid}.")
        return v

    @field_validator("execution_time_ms")
    @classmethod
    def execution_time_non_negative(cls, v: Optional[int]) -> Optional[int]:
        if v is not None and v < 0:
            raise ValueError("execution_time_ms must be non-negative.")
        return v


# ---------------------------------------------------------------------------
# Response schemas
# ---------------------------------------------------------------------------

class RunResponse(BaseModel):
    """Safe public representation of a run.

    Never exposes internal ownership logic; user_id is included on the
    agent but the frontend should treat it as owner-only.
    """

    id: int
    agent_id: int
    task_id: Optional[int]
    status: str
    started_at: datetime
    completed_at: Optional[datetime]
    execution_time_ms: Optional[int]
    error_message: Optional[str]
    created_at: datetime

    model_config = {"from_attributes": True}


class RunListItem(BaseModel):
    """Minimal run representation for list endpoints."""

    id: int
    agent_id: int
    task_id: Optional[int]
    status: str
    started_at: datetime
    completed_at: Optional[datetime]

    model_config = {"from_attributes": True}