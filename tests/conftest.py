"""Shared fixtures for tests."""

import json
from pathlib import Path

import pytest

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture
def openapi_spec() -> dict:
    """Load the offline OpenAPI spec fixture."""
    with open(FIXTURES_DIR / "openapi_spec.json") as f:
        return json.load(f)
