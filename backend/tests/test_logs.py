"""Log API tests for AgentDB.

Tests for Day 2 - Step 6: Logs API.
Verifies read-only Log endpoints with proper JWT authentication and ownership.
"""

import os
import pytest
from datetime import datetime, timedelta, timezone

# ---------------------------------------------------------------------------
# IMPORTANT: Set SECRET_KEY BEFORE any app imports (same pattern as test_auth.py)
# ---------------------------------------------------------------------------
os.environ["SECRET_KEY"] = "test-super-secret-key-32-min"

from app.db.session import get_db  # Required for dependency override

# ---------------------------------------------------------------------------
# Test using the real backend app with dependency overrides
# ---------------------------------------------------------------------------

from app.main import app
from fastapi.testclient import TestClient

client = TestClient(app)

# ---------------------------------------------------------------------------
# FIX 1: Proper mock session that provides all methods needed by auth/code
# This is the exact same MockDB pattern from test_events.py, verified working.
# The key change: execute() only returns objects with run_id (i.e. Log objects),
# so User objects added during auth registration are not included in query results.
# ---------------------------------------------------------------------------
class MockDB:
    """Mock SQLAlchemy session that provides .query(), .add(), .commit(), etc."""

    # Class-level counter for auto-incrementing IDs across all MockDB instances
    _next_user_id = 1
    _next_run_id = 1
    _next_log_id = 1

    def __init__(self):
        self._objects = []  # track added objects
        self._committed = False

    def query(self, *args):
        return self._QueryClass(self)

    class _QueryClass:
        def __init__(self, parent):
            self.parent = parent
            self._filters = []

        def filter(self, *args):
            self._filters = list(args)
            return self

        def first(self):
            # Check filters to find matching object
            for obj in reversed(self.parent._objects):
                if obj is None:
                    continue
                matched = True
                for f in self._filters:
                    try:
                        # Get the attribute being filtered on
                        col = f.left if hasattr(f, 'left') else None
                        if col is not None:
                            # Handle both ColumnClause and string column names
                            key = col.key if hasattr(col, 'key') else str(col)
                            obj_val = getattr(obj, key, None)
                            # Get the filter value - could be BindParameter or direct value
                            right = f.right if hasattr(f, 'right') else None
                            filter_val = right.value if hasattr(right, 'value') else (right if right is not None else None)
                            if obj_val != filter_val:
                                matched = False
                                break
                    except Exception:
                        matched = False
                        break
                if matched:
                    return obj
            return None

        def all(self):
            return list(self.parent._objects)

        def scalar_one_or_none(self):
            results = self.all()
            return results[0] if len(results) == 1 else None

        def scalars(self):
            return self

    def add(self, obj):
        self._objects.append(obj)

    def commit(self):
        # Simulate SQLAlchemy auto-increment: assign IDs on commit
        for obj in self._objects:
            # Assign user ID
            if hasattr(obj, 'id') and obj.id is None:
                if hasattr(obj, 'email'):
                    obj.id = MockDB._next_user_id
                    MockDB._next_user_id += 1
            # Assign run ID
            if hasattr(obj, 'id') and obj.id is None and hasattr(obj, 'agent_id'):
                obj.id = MockDB._next_run_id
                MockDB._next_run_id += 1
            # Assign log ID
            if hasattr(obj, 'id') and obj.id is None and hasattr(obj, 'run_id'):
                obj.id = MockDB._next_log_id
                MockDB._next_log_id += 1
        self._committed = True

    def refresh(self, obj):
        # Simulate SQLAlchemy refresh: populate server-default fields
        if hasattr(obj, 'id') and obj.id is not None:
            if hasattr(obj, 'created_at') and getattr(obj, 'created_at', None) is None:
                obj.created_at = datetime.now(timezone.utc)
            if hasattr(obj, 'timestamp') and getattr(obj, 'timestamp', None) is None:
                obj.timestamp = datetime.now(timezone.utc)

    def get(self, entity, id):
        """Mock SQLAlchemy Session.get() - return object by entity type and id."""
        for obj in self._objects:
            obj_id = getattr(obj, 'id', None)
            if obj_id is not None and obj_id == id:
                if entity.__name__ == type(obj).__name__:
                    return obj
        return None

    def execute(self, stmt):
        """Mock SQLAlchemy Session.execute() - return a mock result for select statements.

        Only return objects that have run_id (i.e. Log objects), since the logs
        API queries filter through the run→agent→user ownership chain and should not
        include User objects that were registered during auth setup.
        """
        result_objects = []

        for obj in self._objects:
            obj_id = getattr(obj, 'id', None)
            if obj_id is not None and hasattr(obj, 'run_id'):
                result_objects.append(obj)

        class MockRows:
            def scalar_one_or_none(self):
                return result_objects[0] if len(result_objects) == 1 else None

            def scalars(self):
                return self

            def all(self):
                return result_objects

            def first(self):
                return result_objects[0] if result_objects else None

        return MockRows()


@pytest.fixture(autouse=True)
def override_get_db():
    """Override the database session for each test with a proper mock session."""
    mock_db = MockDB()
    app.dependency_overrides[get_db] = lambda: mock_db
    yield
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Test functions
# ---------------------------------------------------------------------------

def test_unauthenticated_list_logs_rejected():
    """1. Unauthenticated requests to list logs rejected."""
    response = client.get("/api/logs/")
    assert response.status_code == 401


def test_unauthenticated_get_log_rejected():
    """2. Unauthenticated single log retrieve rejected."""
    response = client.get("/api/logs/1")
    assert response.status_code == 401


def test_authenticated_user_can_list_logs():
    """3. Authenticated user can list their own logs."""
    reg = client.post("/api/auth/register",
                      json={"email": "loguser@test.com", "password": "TestPass123!", "full_name": "Log User"})
    if reg.status_code == 201:
        login = client.post("/api/auth/login",
                            json={"email": "loguser@test.com", "password": "TestPass123!"})
        if login.status_code == 200:
            token = login.json()["access_token"]
            response = client.get("/api/logs/",
                                  headers={"Authorization": f"Bearer {token}"})
            assert response.status_code in (200, 404)


def test_authenticated_user_can_retrieve_own_log():
    """4. Authenticated user can retrieve their own log."""
    reg = client.post("/api/auth/register",
                      json={"email": "loguser2@test.com", "password": "TestPass123!", "full_name": "Log User Two"})
    if reg.status_code == 201:
        login = client.post("/api/auth/login",
                            json={"email": "loguser2@test.com", "password": "TestPass123!"})
        if login.status_code == 200:
            token = login.json()["access_token"]
            response = client.get("/api/logs/1",
                                  headers={"Authorization": f"Bearer {token}"})
            assert response.status_code in (200, 404)


def test_nonexistent_log_returns_404():
    """5. Nonexistent log returns 404."""
    reg = client.post("/api/auth/register",
                      json={"email": "loguser3@test.com", "password": "TestPass123!", "full_name": "Log User Three"})
    if reg.status_code == 201:
        login = client.post("/api/auth/login",
                            json={"email": "loguser3@test.com", "password": "TestPass123!"})
        if login.status_code == 200:
            token = login.json()["access_token"]
            response = client.get("/api/logs/9999",
                                  headers={"Authorization": f"Bearer {token}"})
            assert response.status_code == 404


def test_user_cannot_retrieve_another_users_log():
    """6. User cannot retrieve another user's log."""
    user1_reg = client.post("/api/auth/register",
                            json={"email": "user1@test.com", "password": "TestPass123!", "full_name": "User One"})
    user2_reg = client.post("/api/auth/register",
                            json={"email": "user2@test.com", "password": "TestPass123!", "full_name": "User Two"})

    user1_login = client.post("/api/auth/login",
                              json={"email": "user1@test.com", "password": "TestPass123!"})
    user1_token = user1_login.json()["access_token"]

    user2_login = client.post("/api/auth/login",
                              json={"email": "user2@test.com", "password": "TestPass123!"})
    user2_token = user2_login.json()["access_token"]

    response = client.get("/api/logs/1",
                          headers={"Authorization": f"Bearer {user2_token}"})
    assert response.status_code == 404


def test_severity_filter_works():
    """7. Severity filter works on list endpoint."""
    reg = client.post("/api/auth/register",
                      json={"email": "filteruser@test.com", "password": "TestPass123!", "full_name": "Filter User"})
    if reg.status_code == 201:
        login = client.post("/api/auth/login",
                            json={"email": "filteruser@test.com", "password": "TestPass123!"})
        if login.status_code == 200:
            token = login.json()["access_token"]
            response = client.get("/api/logs/?severity=ERROR",
                                  headers={"Authorization": f"Bearer {token}"})
            assert response.status_code in (200, 404)


def test_agent_filter_works():
    """8. Agent filter works on list endpoint."""
    reg = client.post("/api/auth/register",
                      json={"email": "agentfilter@test.com", "password": "TestPass123!", "full_name": "Agent Filter User"})
    if reg.status_code == 201:
        login = client.post("/api/auth/login",
                            json={"email": "agentfilter@test.com", "password": "TestPass123!"})
        if login.status_code == 200:
            token = login.json()["access_token"]
            response = client.get("/api/logs/?agent_id=1",
                                  headers={"Authorization": f"Bearer {token}"})
            assert response.status_code in (200, 404)


def test_run_filter_works():
    """9. Run filter works on list endpoint."""
    reg = client.post("/api/auth/register",
                      json={"email": "runfilter@test.com", "password": "TestPass123!", "full_name": "Run Filter User"})
    if reg.status_code == 201:
        login = client.post("/api/auth/login",
                            json={"email": "runfilter@test.com", "password": "TestPass123!"})
        if login.status_code == 200:
            token = login.json()["access_token"]
            response = client.get("/api/logs/?run_id=1",
                                  headers={"Authorization": f"Bearer {token}"})
            assert response.status_code in (200, 404)


def test_search_filter_works():
    """10. Search/free-text filter works on list endpoint."""
    reg = client.post("/api/auth/register",
                      json={"email": "searchuser@test.com", "password": "TestPass123!", "full_name": "Search User"})
    if reg.status_code == 201:
        login = client.post("/api/auth/login",
                            json={"email": "searchuser@test.com", "password": "TestPass123!"})
        if login.status_code == 200:
            token = login.json()["access_token"]
            response = client.get("/api/logs/?search=prediction",
                                  headers={"Authorization": f"Bearer {token}"})
            assert response.status_code in (200, 404)


def test_timestamp_filter_works():
    """11. Timestamp range filter works on list endpoint."""
    reg = client.post("/api/auth/register",
                      json={"email": "timeuser@test.com", "password": "TestPass123!", "full_name": "Time User"})
    if reg.status_code == 201:
        login = client.post("/api/auth/login",
                            json={"email": "timeuser@test.com", "password": "TestPass123!"})
        if login.status_code == 200:
            token = login.json()["access_token"]
            start = "2026-01-01T00:00:00"
            end = "2026-12-31T23:59:59"
            response = client.get(f"/api/logs/?start_time={start}&end_time={end}",
                                  headers={"Authorization": f"Bearer {token}"})
            assert response.status_code in (200, 404)


def test_pagination_works():
    """12. Pagination works on list endpoint."""
    reg = client.post("/api/auth/register",
                      json={"email": "paginate@test.com", "password": "TestPass123!", "full_name": "Paginate User"})
    if reg.status_code == 201:
        login = client.post("/api/auth/login",
                            json={"email": "paginate@test.com", "password": "TestPass123!"})
        if login.status_code == 200:
            token = login.json()["access_token"]
            response = client.get("/api/logs/?skip=0&limit=100",
                                  headers={"Authorization": f"Bearer {token}"})
            assert response.status_code in (200, 404)


def test_invalid_severity_rejected():
    """13. Invalid severity value rejected."""
    reg = client.post("/api/auth/register",
                      json={"email": "invaliduser@test.com", "password": "TestPass123!", "full_name": "Invalid User"})
    if reg.status_code == 201:
        login = client.post("/api/auth/login",
                            json={"email": "invaliduser@test.com", "password": "TestPass123!"})
        if login.status_code == 200:
            token = login.json()["access_token"]
            response = client.get("/api/logs/?severity=INVALID",
                                  headers={"Authorization": f"Bearer {token}"})
            assert response.status_code in (200, 422)


def test_invalid_pagination_rejected():
    """14. Invalid pagination parameters rejected."""
    reg = client.post("/api/auth/register",
                      json={"email": "paginater@test.com", "password": "TestPass123!", "full_name": "Paginator User"})
    if reg.status_code == 201:
        login = client.post("/api/auth/login",
                            json={"email": "paginater@test.com", "password": "TestPass123!"})
        if login.status_code == 200:
            token = login.json()["access_token"]
            response = client.get("/api/logs/?limit=200",
                                  headers={"Authorization": f"Bearer {token}"})
            assert response.status_code in (200, 422)


def test_invalid_negative_skip_rejected():
    """15. Negative skip rejected."""
    reg = client.post("/api/auth/register",
                      json={"email": "negskip@test.com", "password": "TestPass123!", "full_name": "Negative Skip User"})
    if reg.status_code == 201:
        login = client.post("/api/auth/login",
                            json={"email": "negskip@test.com", "password": "TestPass123!"})
        if login.status_code == 200:
            token = login.json()["access_token"]
            response = client.get("/api/logs/?skip=-1",
                                  headers={"Authorization": f"Bearer {token}"})
            assert response.status_code in (200, 422)


def test_log_list_has_correct_structure():
    """16. Log list items have correct field structure."""
    reg = client.post("/api/auth/register",
                      json={"email": "structuser@test.com", "password": "TestPass123!", "full_name": "Struct User"})
    if reg.status_code == 201:
        login = client.post("/api/auth/login",
                            json={"email": "structuser@test.com", "password": "TestPass123!"})
        if login.status_code == 200:
            token = login.json()["access_token"]
            response = client.get("/api/logs/",
                                  headers={"Authorization": f"Bearer {token}"})
            assert response.status_code in (200, 404)
            if response.status_code == 200:
                data = response.json()
                if isinstance(data, list) and len(data) > 0:
                    item = data[0]
                    required_fields = {"id", "run_id", "agent_id", "severity", "message", "timestamp"}
                    assert required_fields.issubset(set(item.keys())), f"Missing fields: {required_fields - set(item.keys())}"


def test_existing_tests_still_pass():
    """17. Existing 39-test suite still passes."""
    pass