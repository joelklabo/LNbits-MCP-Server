"""Tests for utils.runtime_config module."""

from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

from lnbits_mcp_server.client import LNbitsConfig
from lnbits_mcp_server.utils.runtime_config import RuntimeConfigManager


class TestUpdateConfiguration:
    async def test_update_configuration_success(self):
        mgr = RuntimeConfigManager()
        result = await mgr.update_configuration(
            lnbits_url="https://my.lnbits.com",
            api_key="secret-key",
        )
        assert result["success"] is True
        # URL updated
        assert "my.lnbits.com" in result["config"]["lnbits_url"]
        # Key is masked
        assert result["config"]["api_key"] == "***MASKED***"

    async def test_update_configuration_rollback_on_invalid(self):
        mgr = RuntimeConfigManager()
        original_url = str(mgr.config.lnbits_url)
        with pytest.raises(ValidationError):
            await mgr.update_configuration(lnbits_url="not-a-url")
        # Config should be unchanged
        assert str(mgr.config.lnbits_url) == original_url


class TestSafeConfig:
    async def test_safe_config_masks_secrets(self):
        mgr = RuntimeConfigManager()
        await mgr.update_configuration(
            lnbits_url="https://example.com",
            api_key="key1",
            bearer_token="bt1",
            oauth2_token="oa1",
            access_token="at1",
        )
        status = mgr.get_configuration_status()
        cfg = status["config"]
        assert cfg["api_key"] == "***MASKED***"
        assert cfg["bearer_token"] == "***MASKED***"
        assert cfg["oauth2_token"] == "***MASKED***"
        assert cfg["access_token"] == "***MASKED***"


class TestConfigChangedCallback:
    async def test_on_config_changed_callback_fires(self):
        mgr = RuntimeConfigManager()
        callback = AsyncMock()
        mgr.on_config_changed = callback
        await mgr.update_configuration(
            lnbits_url="https://example.com",
            api_key="key",
        )
        callback.assert_awaited_once()


class TestGetClient:
    async def test_get_client_creates_once(self):
        mgr = RuntimeConfigManager()
        client1 = await mgr.get_client()
        client2 = await mgr.get_client()
        assert client1 is client2


class TestAccessToken:
    async def test_access_token_in_update(self):
        mgr = RuntimeConfigManager()
        await mgr.update_configuration(
            lnbits_url="https://example.com",
            access_token="jwt-token-123",
        )
        assert mgr.config.access_token == "jwt-token-123"
