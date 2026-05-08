# Input: FastAPI TestClient pointed at backend.main:app
# Output: Unit tests for POST /api/ingest — request validation, file existence
# Position: Test coverage for the tree ingest endpoint. If modified, update
#   this header.

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.main import app

client = TestClient(app)


class TestIngestRequestValidation:
    """Pydantic model validation (no DB or LLM needed)."""

    def test_missing_file_path(self):
        resp = client.post("/api/ingest", json={
            "company_name": "TestCo",
            "year_period": "2022",
        })
        assert resp.status_code == 422

    def test_missing_company_name(self):
        resp = client.post("/api/ingest", json={
            "file_path": "/tmp/test.pdf",
            "year_period": "2022",
        })
        assert resp.status_code == 422

    def test_missing_year_period(self):
        resp = client.post("/api/ingest", json={
            "file_path": "/tmp/test.pdf",
            "company_name": "TestCo",
        })
        assert resp.status_code == 422

    def test_nonexistent_file_returns_400(self):
        resp = client.post("/api/ingest", json={
            "file_path": "/tmp/nonexistent_file_xyz.pdf",
            "company_name": "TestCo",
            "year_period": "2022",
        })
        assert resp.status_code == 400
        assert "not found" in resp.json()["detail"].lower()
