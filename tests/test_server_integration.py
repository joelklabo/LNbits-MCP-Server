"""Integration tests: end-to-end list_tools / call_tool with offline spec."""

import json
from unittest.mock import AsyncMock, patch

import pytest

from lnbits_mcp_server.discovery.meta_tools import META_TOOL_NAMES
from lnbits_mcp_server.discovery.openapi_parser import OpenAPIParser
from lnbits_mcp_server.discovery.tool_registry import ToolRegistry
from lnbits_mcp_server.discovery.dispatcher import Dispatcher
from lnbits_mcp_server.discovery.meta_tools import MetaTools
from lnbits_mcp_server.utils.runtime_config import RuntimeConfigManager
from lnbits_mcp_server.client import LNbitsConfig


@pytest.fixture
def registry(openapi_spec):
    parser = OpenAPIParser("http://localhost:5000")
    ops = parser.parse_spec_dict(openapi_spec)
    reg = ToolRegistry()
    reg.load(ops)
    return reg


@pytest.fixture
def config_manager():
    return RuntimeConfigManager(LNbitsConfig(lnbits_url="http://localhost:5000"))


class TestEndToEnd:
    def test_list_tools_returns_meta_plus_discovered(self, registry):
        meta = MetaTools.get_tools()
        discovered = registry.get_mcp_tools()
        combined = meta + discovered
        meta_names = {t.name for t in meta}
        discovered_names = {t.name for t in discovered}
        assert meta_names == META_TOOL_NAMES
        assert len(discovered_names) > 0
        assert meta_names.isdisjoint(discovered_names)

    def test_discovered_tools_all_have_api_paths(self, registry):
        for op in registry._operations.values():
            assert "/api/" in op.path

    def test_no_delete_in_default_config(self, registry):
        for op in registry._operations.values():
            assert op.method != "DELETE"

    @pytest.mark.asyncio
    async def test_call_discovered_tool(self, registry, config_manager):
        """Simulate calling a discovered tool via the dispatcher."""
        dispatcher = Dispatcher()
        mock_client = AsyncMock()
        mock_client._request = AsyncMock(return_value={"id": "wallet1", "balance": 5000})

        # Find the wallet GET tool
        wallet_tool = None
        for name, op in registry._operations.items():
            if op.path == "/api/v1/wallet" and op.method == "GET":
                wallet_tool = op
                break

        assert wallet_tool is not None
        result = await dispatcher.dispatch(mock_client, wallet_tool, {})
        parsed = json.loads(result)
        assert parsed["id"] == "wallet1"

    @pytest.mark.asyncio
    async def test_call_meta_tool(self, config_manager):
        """Simulate calling a meta tool."""
        meta = MetaTools(config_manager)
        meta.set_callbacks(
            refresh_fn=AsyncMock(return_value=10),
            get_extensions_fn=lambda: {"lnurlp": 3},
        )
        result = await meta.call_tool("list_extensions", {})
        parsed = json.loads(result)
        assert parsed["extensions"]["lnurlp"] == 3

    def test_tool_names_do_not_collide_with_meta(self, registry):
        """Discovered tool names should never shadow meta tool names."""
        for name in registry.tool_names:
            assert name not in META_TOOL_NAMES, f"Collision: {name}"
