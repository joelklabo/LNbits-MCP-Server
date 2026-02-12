"""Tests for discovery.meta_tools."""

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from lnbits_mcp_server.discovery.meta_tools import META_TOOL_NAMES, MetaTools


@pytest.fixture
def config_manager():
    mgr = AsyncMock()
    mgr.update_configuration = AsyncMock(
        return_value={"success": True, "message": "ok"}
    )
    mgr.test_configuration = AsyncMock(
        return_value={"success": True, "message": "Connected"}
    )
    mgr.get_configuration_status = MagicMock(
        return_value={
            "is_configured": True,
            "config": {"lnbits_url": "http://localhost"},
        }
    )
    return mgr


@pytest.fixture
def meta_tools(config_manager):
    mt = MetaTools(config_manager)
    mt.set_callbacks(
        refresh_fn=AsyncMock(return_value=42),
        get_extensions_fn=MagicMock(return_value={"lnurlp": 5, "core": 10}),
    )
    return mt


class TestMetaToolDefinitions:
    def test_tool_count(self):
        tools = MetaTools.get_tools()
        assert len(tools) == 6

    def test_tool_names(self):
        expected = {
            "configure_lnbits",
            "test_connection",
            "get_configuration",
            "refresh_tools",
            "list_extensions",
            "pay_lightning_address",
        }
        assert META_TOOL_NAMES == expected

    def test_all_have_schemas(self):
        for tool in MetaTools.get_tools():
            assert tool.inputSchema is not None
            assert tool.inputSchema["type"] == "object"


class TestMetaToolCalls:
    @pytest.mark.asyncio
    async def test_configure(self, meta_tools, config_manager):
        result = await meta_tools.call_tool(
            "configure_lnbits",
            {"lnbits_url": "http://new-host:5000"},
        )
        parsed = json.loads(result)
        assert parsed["success"]
        config_manager.update_configuration.assert_called_once()

    @pytest.mark.asyncio
    async def test_test_connection(self, meta_tools, config_manager):
        result = await meta_tools.call_tool("test_connection", {})
        parsed = json.loads(result)
        assert parsed["success"]

    @pytest.mark.asyncio
    async def test_get_configuration(self, meta_tools):
        result = await meta_tools.call_tool("get_configuration", {})
        parsed = json.loads(result)
        assert "is_configured" in parsed

    @pytest.mark.asyncio
    async def test_refresh_tools(self, meta_tools):
        result = await meta_tools.call_tool("refresh_tools", {})
        parsed = json.loads(result)
        assert parsed["success"]
        assert parsed["tool_count"] == 42

    @pytest.mark.asyncio
    async def test_list_extensions(self, meta_tools):
        result = await meta_tools.call_tool("list_extensions", {})
        parsed = json.loads(result)
        assert "extensions" in parsed
        assert parsed["extensions"]["lnurlp"] == 5
        assert parsed["total_tools"] == 15

    @pytest.mark.asyncio
    async def test_unknown_tool_raises(self, meta_tools):
        with pytest.raises(ValueError, match="Unknown meta tool"):
            await meta_tools.call_tool("nonexistent", {})
