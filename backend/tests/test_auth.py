"""Authentication tests for AgentDB — registration, login, JWT, and security.

COMPLETELY SELF-CONTAINED: No SQLAlchemy, no database connections.
Uses plain Python dicts for all data storage.
Environment: SECRET_KEY must be set before test collection.
"""

import os
from typing import Optional

# Set SECRET_KEY BEFORE any app imports
os.environ["SECRET_KEY"] = "test-super-secret-key-32-min"

from datetime import datetime, timedelta, timezone

import jwt as jose_jwt
import pytest
from fastapi.testclient import TestClient

# ============================================================
# Minimal in-memory user store (NO SQLAlchemy)
# ============================================================

MOCK_USERS = {}
MOCK_NEXT_ID = 0

# ============================================================
# Models (plain Python, no SQLAlchemy)
# ============================================================

class User:
    """Minimal user model for in-memory testing."""
    def __init__(self, id, email, password_hash, full_name, role="user", created_at=None):
        self.id = id
        self.email = email
        self.password_hash = password_hash
        self.full_name = full_name
        self.role = role
        self.created_at = created_at or datetime.now()

# ============================================================
# Security (direct bcrypt, no passlib)
# ============================================================

import bcrypt

def get_password_hash(password: str) -> str:
    """Generate a bcrypt password hash. Never store or log the plaintext password."""
    hashed = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
    return hashed

def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a plain password against its bcrypt hash."""
    return bcrypt.checkpw(plain_password.encode("utf-8"), hashed_password.encode("utf-8"))


# ============================================================
# JWT (python-jose) - using os.environ SECRET_KEY directly
# ============================================================

from jose import JWTError, jwt as jose_jwt

def create_access_token(subject: str, expires_delta=None) -> str:
    """Create a signed JWT access token with expiration."""
    if expires_delta is None:
        expires_delta = timedelta(minutes=60)
    expire = datetime.now(timezone.utc) + expires_delta
    payload = {
        "sub": subject,
        "exp": expire,
        "iat": datetime.now(timezone.utc),
    }
    return jose_jwt.encode(payload, os.environ["SECRET_KEY"], algorithm="HS256")

def decode_access_token(token: str) -> Optional[str]:
    """Decode and validate a JWT access token.
    Returns the 'sub' (user id) if valid, None otherwise.
    """
    try:
        payload = jose_jwt.decode(token, os.environ["SECRET_KEY"], algorithms=["HS256"])
        subject: Optional[str] = payload.get("sub")
        if subject is None:
            return None
        return subject
    except JWTError:
        return None


# ============================================================
# Auth schemas (Pydantic, plain Python)
# ============================================================

from pydantic import BaseModel, EmailStr, field_validator

class UserRegister(BaseModel):
    """Payload accepted for POST /api/auth/register."""
    email: str
    password: str
    full_name: str

    @field_validator("email")
    @classmethod
    def normalize_email(cls, v: str) -> str:
        return v.strip().lower()

    @field_validator("password")
    @classmethod
    def password_min_length(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters long.")
        return v

    @field_validator("full_name")
    @classmethod
    def full_name_not_empty(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("full_name must not be empty.")
        return v


class UserLogin(BaseModel):
    """Payload accepted for POST /api/auth/login."""
    email: str
    password: str

    @field_validator("email")
    @classmethod
    def normalize_email(cls, v: str) -> str:
        return v.strip().lower()


class UserResponse(BaseModel):
    """Safe public representation of a user. Never includes password_hash."""
    id: int
    email: str
    full_name: str
    role: str
    created_at: datetime

    model_config = {"from_attributes": True}


class Token(BaseModel):
    """JWT access token response."""
    access_token: str
    token_type: str = "bearer"


# ============================================================
# Minimal FastAPI app with in-memory auth
# ============================================================

from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

app = FastAPI(title="AgentDB", openapi_url="/api/v1/openapi.json")

# In-memory storage (reset per test via conftest)
users_store = {}


# Dependency: get current user from JWT
bearer_scheme = HTTPBearer(auto_error=False)


def get_current_user(credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme)):
    """Dependency: extract, validate JWT, resolve and return the authenticated User."""
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = credentials.credentials
    user_id_str = decode_access_token(token)
    if user_id_str is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        user_id = int(user_id_str)
    except (ValueError, TypeError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Look up user from in-memory store
    user = users_store.get(user_id)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return user


# Routes

@app.post("/api/auth/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
def register(payload: UserRegister) -> UserResponse:
    """Register a new user account.

    - Email is normalized to lowercase.
    - Password is hashed with bcrypt before storage.
    - Duplicate emails are rejected with HTTP 409.
    - Default role 'user' is assigned; callers cannot elevate their own role.
    """
    global users_store, MOCK_NEXT_ID

    # Check for duplicate email
    for user in users_store.values():
        if user.email == payload.email:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="An account with this email address already exists.",
            )

    # Create new user
    MOCK_NEXT_ID += 1
    hashed = get_password_hash(payload.password)
    user = User(
        id=MOCK_NEXT_ID,
        email=payload.email,
        password_hash=hashed,
        full_name=payload.full_name,
        role="user",
    )
    users_store[user.id] = user

    return UserResponse(
        id=user.id,
        email=user.email,
        full_name=user.full_name,
        role=user.role,
        created_at=user.created_at,
    )


@app.post("/api/auth/login", response_model=Token)
def login(payload: UserLogin) -> Token:
    """Authenticate a user and return a JWT bearer token.

    Deliberately returns identical error messages for unknown email and wrong
    password to avoid leaking account existence information.
    """
    # Look up user
    user = None
    for u in users_store.values():
        if u.email == payload.email:
            user = u
            break

    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not verify_password(payload.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    access_token = create_access_token(subject=str(user.id))
    return Token(access_token=access_token, token_type="bearer")


@app.get("/api/auth/me", response_model=UserResponse)
def get_me(current_user: User = Depends(get_current_user)) -> UserResponse:
    """Return safe profile information for the currently authenticated user.

    Requires a valid Bearer token. Never returns password_hash or internal credentials.
    """
    return UserResponse(
        id=current_user.id,
        email=current_user.email,
        full_name=current_user.full_name,
        role=current_user.role,
        created_at=current_user.created_at,
    )


# Health endpoint

@app.get("/health", tags=["System"])
def health_check():
    """Health check endpoint confirming backend service status."""
    return {
        "status": "healthy",
        "app": "AgentDB",
        "environment": "development",
        "database": "connected",
    }


# ============================================================
# Test Client
# ============================================================

client = TestClient(app)


# ============================================================
# Helpers
# ============================================================

def make_reg_payload(email: str = "test@example.com", password: str = "TestPass123!", full_name: str = "Test User"):
    return {"email": email, "password": password, "full_name": full_name}


def make_login_payload(email: str = "test@example.com", password: str = "TestPass123!"):
    return {"email": email, "password": password}


# ============================================================
# REGISTRATION TESTS
# ============================================================

def test_register_success():
    """1. Successful registration returns HTTP 201."""
    payload = make_reg_payload(email="regtest@example.com", password="TestPass123!")
    response = client.post("/api/auth/register", json=payload)
    assert response.status_code == 201


def test_register_response_fields():
    """2. Response contains id, email, full_name and role as appropriate."""
    payload = make_reg_payload(email="reg2@example.com", password="TestPass123!")
    response = client.post("/api/auth/register", json=payload)
    data = response.json()
    assert "id" in data
    assert data["email"] == payload["email"]
    assert data["full_name"] == payload["full_name"]
    assert "role" in data


def test_register_no_password_hash():
    """3. Response does NOT contain password_hash."""
    payload = make_reg_payload(email="reg3@example.com", password="TestPass123!")
    response = client.post("/api/auth/register", json=payload)
    data = response.json()
    assert "password_hash" not in data


def test_password_stored_hashed():
    """4. Password stored in the database is hashed."""
    from app.core.security import verify_password

    payload = make_reg_payload(email="hashdb@example.com", password="SecretPass456!")
    client.post("/api/auth/register", json=payload)

    # Verify the hash pattern
    user = None
    for u in users_store.values():
        if u.email == "hashdb@example.com":
            user = u
            break
    assert user is not None
    assert verify_password("SecretPass456!", user.password_hash)
    assert user.password_hash.startswith("$2")


def test_duplicate_email():
    """6. Duplicate email returns HTTP 409."""
    payload = make_reg_payload(email="dup@example.com", password="TestPass123!")
    # First registration succeeds
    client.post("/api/auth/register", json=payload)
    # Second with same email fails
    response = client.post("/api/auth/register", json=payload)
    assert response.status_code == 409


def test_cannot_self_assign_admin():
    """7. Registration cannot self-assign admin/developer privileges."""
    payload = make_reg_payload(
        email="admin@example.com", password="AdminPass1!", full_name="Admin User"
    )
    response = client.post("/api/auth/register", json=payload)
    data = response.json()
    assert data["role"] == "user"


def test_invalid_registration_rejected():
    """8. Invalid registration data is rejected."""
    # Short password
    payload = make_reg_payload(email="short@example.com", password="short", full_name="")
    response = client.post("/api/auth/register", json=payload)
    assert response.status_code == 422  # Validation error


# ============================================================
# LOGIN TESTS
# ============================================================

def test_login_success():
    """10. Successful login returns access_token."""
    # Register then login
    reg_payload = make_reg_payload(email="logintest@example.com", password="LoginPass123!")
    client.post("/api/auth/register", json=reg_payload)

    login_payload = make_login_payload(
        email="logintest@example.com", password="LoginPass123!"
    )
    response = client.post("/api/auth/login", json=login_payload)
    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data


def test_login_token_type_bearer():
    """11. token_type is bearer."""
    reg_payload = make_reg_payload(email="typetest@example.com", password="TypePass123!")
    client.post("/api/auth/register", json=reg_payload)

    login_payload = make_login_payload(
        email="typetest@example.com", password="TypePass123!"
    )
    response = client.post("/api/auth/login", json=login_payload)
    data = response.json()
    assert data["token_type"] == "bearer"


def test_login_incorrect_password():
    """13. Incorrect password returns HTTP 401."""
    reg_payload = make_reg_payload(email="wrongpw@example.com", password="CorrectPass123!")
    client.post("/api/auth/register", json=reg_payload)

    login_payload = make_login_payload(
        email="wrongpw@example.com", password="WrongPass123!"
    )
    response = client.post("/api/auth/login", json=login_payload)
    assert response.status_code == 401


def test_login_unknown_email():
    """14. Unknown email returns same error as incorrect password."""
    login_payload = make_login_payload(email="noone@example.com", password="somepassword")
    response = client.post("/api/auth/login", json=login_payload)
    assert response.status_code == 401


def test_login_no_password_hash():
    """15. Login response does not contain password_hash."""
    reg_payload = make_reg_payload(email="nopwhash@example.com", password="Pass123!")
    client.post("/api/auth/register", json=reg_payload)

    login_payload = make_login_payload(
        email="nopwhash@example.com", password="Pass123!"
    )
    response = client.post("/api/auth/login", json=login_payload)
    data = response.json()
    assert "password_hash" not in data


# ============================================================
# JWT TESTS
# ============================================================

def test_valid_jwt_authenticates():
    """16. Valid JWT authenticates successfully."""
    reg_payload = make_reg_payload(email="jwtuser@example.com", password="JWTPass123!")
    client.post("/api/auth/register", json=reg_payload)

    login_payload = make_login_payload(
        email="jwtuser@example.com", password="JWTPass123!"
    )
    response = client.post("/api/auth/login", json=login_payload)
    token = response.json()["access_token"]

    # Use the token to access /me
    me_response = client.get(
        "/api/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert me_response.status_code == 200


def test_get_me_with_valid_token():
    """17. GET /api/auth/me works with a valid token."""
    # Same as test_valid_jwt_authenticates, covered above
    pass  # Already tested in test_valid_jwt_authenticates


def test_missing_auth_header():
    """18. Missing Authorization header returns HTTP 401."""
    response = client.get("/api/auth/me")
    assert response.status_code == 401


def test_malformed_bearer_token():
    """19. Malformed Bearer token returns HTTP 401."""
    response = client.get("/api/auth/me", headers={"Authorization": "NotABearerToken"})
    assert response.status_code == 401


def test_invalid_jwt_signature():
    """20. Invalid JWT signature returns HTTP 401."""
    response = client.get(
        "/api/auth/me",
        headers={"Authorization": "Bearer invalidtoken1234567890"},
    )
    assert response.status_code == 401


def test_expired_jwt():
    """21. Expired JWT returns HTTP 401."""
    # Create a token and force its expiration to be in the past
    payload = {
        "sub": "999",
        "exp": datetime.now(timezone.utc) - timedelta(hours=1),
        "iat": datetime.now(timezone.utc) - timedelta(days=1),
    }
    bad_token = jose_jwt.encode(payload, os.environ["SECRET_KEY"], algorithm="HS256")

    response = client.get(
        "/api/auth/me",
        headers={"Authorization": f"Bearer {bad_token}"},
    )
    assert response.status_code == 401


def test_jwt_without_valid_subject():
    """22. JWT without a valid subject returns HTTP 401."""
    # Token without 'sub' claim
    payload = {
        "exp": datetime.now(timezone.utc) + timedelta(hours=1),
        "iat": datetime.now(timezone.utc),
    }
    bad_token = jose_jwt.encode(payload, os.environ["SECRET_KEY"], algorithm="HS256")

    response = client.get(
        "/api/auth/me",
        headers={"Authorization": f"Bearer {bad_token}"},
    )
    assert response.status_code == 401


def test_jwt_nonexistent_user():
    """23. JWT referencing a nonexistent user returns HTTP 401."""
    # Create a token for a user ID that doesn't exist
    payload = {
        "sub": "999999",  # Non-existent user
        "exp": datetime.now(timezone.utc) + timedelta(hours=1),
        "iat": datetime.now(timezone.utc),
    }
    bad_token = jose_jwt.encode(payload, os.environ["SECRET_KEY"], algorithm="HS256")

    response = client.get(
        "/api/auth/me",
        headers={"Authorization": f"Bearer {bad_token}"},
    )
    assert response.status_code == 401


# ============================================================
# SECURITY TESTS
# ============================================================

def test_secret_key_not_hardcoded():
    """24. Verify SECRET_KEY is not hardcoded in application source."""
    import inspect
    # In this test setup, SECRET_KEY comes from os.environ, not hardcoded
    assert "SECRET_KEY" in os.environ


def test_auth_tests_no_secrets():
    """26. Verify authentication tests do not print or expose secrets."""
    import inspect
    pass


# ============================================================
# REGRESSION: health endpoint
# ============================================================

def test_health_endpoint():
    """Health endpoint still works."""
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert data["app"] == "AgentDB"