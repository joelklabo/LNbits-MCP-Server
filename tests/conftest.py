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


@pytest.fixture
def live_openapi_spec() -> dict:
    """Load the live OpenAPI spec fixture (from lnbits.klabo.world)."""
    with open(FIXTURES_DIR / "openapi_spec_live.json") as f:
        return json.load(f)
