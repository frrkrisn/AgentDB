from fastapi.testclient import TestClient
from app.main import app
from app.db.session import get_db

client = TestClient(app)


def test_health_endpoint():
    """Test GET /health API endpoint structure and mock database connection response."""
    def override_get_db():
        class MockDB:
            def execute(self, query):
                return [(1,)]
        yield MockDB()

    app.dependency_overrides[get_db] = override_get_db
    try:
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert data["app"] == "AgentDB"
        assert data["database"] == "connected"
    finally:
        app.dependency_overrides.clear()
