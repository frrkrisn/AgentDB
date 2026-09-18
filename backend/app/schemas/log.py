"""Log Management API schemas for AgentDB.

Pydantic v2 schemas for Log endpoints.
Follows the same patterns as Event and Run schemas.
"""

from datetime import datetime
from typing import Optional
from pydantic import BaseModel, field_validator


# ---------------------------------------------------------------------------
# Request/response schemas
# ---------------------------------------------------------------------------


class LogResponse(BaseModel):
    """Safe public representation of a log."""

    id: int
    run_id: int
    agent_id: int
    severity: str
    message: str
    metadata: Optional[dict]
    timestamp: datetime

    model_config = {"from_attributes": True}


class LogListItem(BaseModel):
    """Minimal log representation for list endpoints."""

    id: int
    run_id: int
    agent_id: int
    severity: str
    message: str
    timestamp: datetime

    model_config = {"from_attributes": True}


class LogSeverity(str):
    """Allowed severity values for Log model validation."""

    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"

    model_config = {"validate_by_name": True}

    @classmethod
    def __validators__(cls, v):
        """Validate that severity is one of the allowed values."""
        if v not in ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"):
            raise ValueError("Severity must be one of: DEBUG, INFO, WARNING, ERROR, CRITICAL")
        return v


# ---------------------------------------------------------------------------
# Query/filters schemas
# ---------------------------------------------------------------------------


class LogList(BaseModel):
    """Query parameters for GET /api/logs."""

    skip: int = 0
    limit: int = 100
    severity: Optional[str] = None
    agent_id: Optional[int] = None
    run_id: Optional[int] = None
    search: Optional[str] = None
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None

    @field_validator("skip")
    @classmethod
    def skip_must_be_nonnegative(cls, v: int) -> int:
        if v < 0:
            raise ValueError("skip must be >= 0")
        return v

    @field_validator("limit")
    @classmethod
    def limit_must_be_reasonable(cls, v: int) -> int:
        if v < 1 or v > 100:
            raise ValueError("limit must be between 1 and 100")
        return v