"""Event Management API routers for AgentDB.

Implements Event CRUD endpoints with proper JWT authentication and
ownership enforcement through the chain: User → Agent → Run → Event.

Follows the exact same architecture as the Run API.
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import select

from app.db.session import get_db
from app.api.dependencies import get_current_user
from app.models.user import User
from app.models.agent import Agent
from app.models.run import Run
from app.models.event import Event
from app.schemas.event import EventCreate, EventUpdate, EventResponse, EventListItem

router = APIRouter(prefix="/api/events", tags=["Events"])


# ---------------------------------------------------------------------------
# Helper: verify run ownership
# ---------------------------------------------------------------------------

def _check_run_ownership(db: Session, run_id: int, current_user: User) -> Run:
    """Return run if it belongs to an agent owned by current_user, else raise 404."""
    stmt = select(Run).join(Run.agent).where(Run.id == run_id, Agent.user_id == current_user.id)
    result = db.execute(stmt)
    run = result.scalar_one_or_none()
    if run is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Run not found or not owned by user.",
        )
    return run


# ---------------------------------------------------------------------------
# Helper: verify event belongs to user's run
# ---------------------------------------------------------------------------

def _check_event_ownership(db: Session, event_id: int, current_user: User) -> Event:
    """Return event if it belongs to a run owned by current_user, else raise 404."""
    # First verify the event exists and get its run
    stmt = select(Event).where(Event.id == event_id)
    result = db.execute(stmt)
    event = result.scalar_one_or_none()
    if event is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Event not found.",
        )
    # Now verify the run belongs to user
    return _check_run_ownership(db, event.run_id, current_user)


# ---------------------------------------------------------------------------
# CREATE: POST /api/events
# ---------------------------------------------------------------------------

@router.post(
    "/", response_model=EventResponse, status_code=status.HTTP_201_CREATED
)
def create_event(
    payload: EventCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> EventResponse:
    """Create a new event for a run owned by the authenticated user.

    - run_id must reference a run owned by the user (via agent ownership).
    - event_type and event_name are required.
    - payload is optional structured metadata.
    - Never accepts user_id from the client.
    """
    # Verify the run belongs to the current user
    run = _check_run_ownership(db, payload.run_id, current_user)

    # Create the event
    db_event = Event(
        run_id=payload.run_id,
        event_type=payload.event_type,
        event_name=payload.event_name,
        payload=payload.payload,
    )
    db.add(db_event)
    db.commit()
    db.refresh(db_event)
    return db_event


# ---------------------------------------------------------------------------
# GET SINGLE: GET /api/events/{event_id}
# ---------------------------------------------------------------------------

@router.get(
    "/{event_id}", response_model=EventResponse
)
def get_event(
    event_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> EventResponse:
    """Return the event if it belongs to a run owned by the authenticated user.

    Prevents IDOR - user can only access events from their own runs.
    """
    event = _check_event_ownership(db, event_id, current_user)
    return event


# ---------------------------------------------------------------------------
# LIST: GET /api/events
# ---------------------------------------------------------------------------

@router.get("/", response_model=list[EventListItem])
def list_events(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[EventListItem]:
    """Return only events belonging to the authenticated user's runs.

    Events are filtered through the run → agent → user ownership chain.
    Returns only events from runs belonging to the authenticated user's agents.
    """
    # First get all runs owned by the user
    stmt = select(Run).join(Run.agent).where(Agent.user_id == current_user.id)
    result = db.execute(stmt)
    user_runs = result.scalars().all()
    user_run_ids = {run.id for run in user_runs}

    # List events only from user's runs
    if not user_run_ids:
        return []

    stmt = select(Event).where(Event.run_id.in_(user_run_ids))
    result = db.execute(stmt)
    events = result.scalars().all()
    return events


# ---------------------------------------------------------------------------
# PATCH: PATCH /api/events/{event_id}
# ---------------------------------------------------------------------------

@router.patch(
    "/{event_id}", response_model=EventResponse
)
def update_event(
    event_id: int,
    payload: EventUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> EventResponse:
    """Partial update of an event owned by the authenticated user.

    Only event_name and payload can be updated.
    run_id and event_type cannot be changed after creation.
    """
    event = _check_event_ownership(db, event_id, current_user)

    # Apply only the fields that were provided (partial update)
    update_data = payload.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(event, key, value)

    db.commit()
    db.refresh(event)
    return event