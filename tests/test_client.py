"""Tests for LNbitsConfig and LNbitsClient."""

import httpx
import pytest

from lnbits_mcp_server.client import LNbitsClient, LNbitsConfig, LNbitsError
from lnbits_mcp_server.utils.auth import AuthMethod


# ---------------------------------------------------------------------------
# LNbitsConfig
# ---------------------------------------------------------------------------


class TestLNbitsConfig:
    def test_default_config(self):
        cfg = LNbitsConfig()
        assert str(cfg.lnbits_url) == "https://demo.lnbits.com/"
        assert cfg.api_key is None
        assert cfg.bearer_token is None
        assert cfg.oauth2_token is None
        assert cfg.access_token is None
        assert cfg.auth_method == AuthMethod.API_KEY_HEADER
        assert cfg.timeout == 30
        assert cfg.max_retries == 3
        assert cfg.rate_limit_per_minute == 60

    def test_env_var_loading(self, monkeypatch):
        monkeypatch.setenv("LNBITS_ACCESS_TOKEN", "jwt-tok-123")
        cfg = LNbitsConfig()
        assert cfg.access_token == "jwt-tok-123"

    def test_populate_by_name_roundtrip(self):
        """model_dump() -> LNbitsConfig(**dump) must succeed.

        This is the regression test for the populate_by_name fix.
        """
        original = LNbitsConfig(
            lnbits_url="https://my.lnbits.com",
            api_key="key1",
            timeout=10,
        )
        dumped = original.model_dump()
        restored = LNbitsConfig(**dumped)
        assert str(restored.lnbits_url) == str(original.lnbits_url)
        assert restored.api_key == original.api_key
        assert restored.timeout == original.timeout

    def test_validation_alias(self, monkeypatch):
        monkeypatch.setenv("LNBITS_URL", "https://custom.lnbits.com")
        cfg = LNbitsConfig()
        assert "custom.lnbits.com" in str(cfg.lnbits_url)


# ---------------------------------------------------------------------------
# LNbitsClient
# ---------------------------------------------------------------------------


class TestLNbitsClient:
    async def test_request_success(self, httpx_mock):
        httpx_mock.add_response(
            url="https://demo.lnbits.com/api/v1/wallet",
            json={"balance": 1000},
        )
        async with LNbitsClient() as client:
            result = await client.get("/api/v1/wallet")
        assert result == {"balance": 1000}

    async def test_request_4xx_raises_lnbits_error(self, httpx_mock):
        httpx_mock.add_response(
            url="https://demo.lnbits.com/api/v1/wallet",
            status_code=404,
            json={"detail": "Not found"},
        )
        async with LNbitsClient() as client:
            with pytest.raises(LNbitsError) as exc_info:
                await client.get("/api/v1/wallet")
            assert exc_info.value.status_code == 404

    async def test_request_error_detail_extraction(self, httpx_mock):
        httpx_mock.add_response(
            url="https://demo.lnbits.com/api/v1/payments",
            status_code=400,
            json={"detail": "Insufficient balance"},
        )
        async with LNbitsClient() as client:
            with pytest.raises(LNbitsError, match="Insufficient balance"):
                await client.post("/api/v1/payments", json={"out": True})

    async def test_request_network_error(self, httpx_mock):
        httpx_mock.add_exception(
            httpx.ConnectError("Connection refused"),
            url="https://demo.lnbits.com/api/v1/wallet",
        )
        async with LNbitsClient() as client:
            with pytest.raises(LNbitsError, match="Request failed"):
                await client.get("/api/v1/wallet")

    async def test_auth_headers_applied(self, httpx_mock):
        httpx_mock.add_response(
            url="https://demo.lnbits.com/api/v1/wallet",
            json={"balance": 0},
        )
        cfg = LNbitsConfig(api_key="test-api-key-42")
        async with LNbitsClient(cfg) as client:
            await client.get("/api/v1/wallet")

        request = httpx_mock.get_request()
        assert request.headers["X-API-KEY"] == "test-api-key-42"

    async def test_resolve_lightning_address_invalid_format(self):
        async with LNbitsClient() as client:
            with pytest.raises(LNbitsError, match="Invalid lightning address"):
                await client.resolve_lightning_address("not-an-address")

    async def test_resolve_lightning_address_success(self, httpx_mock):
        httpx_mock.add_response(
            url="https://example.com/.well-known/lnurlp/user",
            json={
                "callback": "https://example.com/lnurlp/cb/1",
                "minSendable": 1000,
                "maxSendable": 100000000,
            },
        )
        async with LNbitsClient() as client:
            result = await client.resolve_lightning_address("user@example.com")
        assert result == "https://example.com/lnurlp/cb/1"

    async def test_check_connection_true(self, httpx_mock):
        httpx_mock.add_response(
            url="https://demo.lnbits.com/api/v1/wallet",
            json={"balance": 0},
        )
        async with LNbitsClient() as client:
            assert await client.check_connection() is True

    async def test_check_connection_false(self, httpx_mock):
        httpx_mock.add_exception(
            httpx.ConnectError("Connection refused"),
            url="https://demo.lnbits.com/api/v1/wallet",
        )
        async with LNbitsClient() as client:
            assert await client.check_connection() is False
