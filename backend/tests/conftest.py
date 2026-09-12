"""Per-test fixtures for AgentDB authentication tests.

Ensures each test starts with a clean in-memory user store.
Manages global state: users_store and MOCK_NEXT_ID.
"""

import os

# Set SECRET_KEY
os.environ["SECRET_KEY"] = "test-super-secret-key-32-min"

import pytest

# Don't import from test_auth - manage state directly


@pytest.fixture(autouse=True, scope="function")
def reset_mock_store():
    """Reset in-memory user store before each test function."""
    global users_store, MOCK_NEXT_ID
    users_store = {}
    MOCK_NEXT_ID = 0
    yield
    # Clean up after test
    users_store = {}
    MOCK_NEXT_ID = 0