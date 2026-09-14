"""Agent Management API tests for AgentDB.

Tests for Day 2 - Step 2: Agent Management APIs.
Verifies CRUD operations with proper JWT authentication and ownership.
"""

import os
import pytest
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import FastAPI
from fastapi.testclient import TestClient
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, EmailStr, field_validator