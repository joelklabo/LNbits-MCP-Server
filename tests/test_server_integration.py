"""Integration tests: end-to-end list_tools / call_tool with offline spec."""

import json
from unittest.mock import AsyncMock, patch

import pytest

from lnbits_mcp_server.client import LNbitsConfig
from lnbits_mcp_server.discovery.dispatcher import Dispatcher
from lnbits_mcp_server.discovery.meta_tools import META_TOOL_NAMES, MetaTools
from lnbits_mcp_server.discovery.openapi_parser import OpenAPIParser
from lnbits_mcp_server.discovery.tool_registry import ToolRegistry
from lnbits_mcp_server.utils.runtime_config import RuntimeConfigManager


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
        mock_client._request = AsyncMock(
            return_value={"id": "wallet1", "balance": 5000}
        )

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

    @pytest.mark.asyncio
    async def test_invoice_creation_includes_qr_code(self, registry):
        """Creating an invoice should enrich response with qr_code and lightning_uri."""
        dispatcher = Dispatcher()
        mock_client = AsyncMock()
        mock_client._request = AsyncMock(
            return_value={"payment_hash": "abc123", "payment_request": "lnbc1234..."}
        )
        mock_client.config = LNbitsConfig(lnbits_url="http://localhost:5000")

        payments_op = None
        for name, op in registry._operations.items():
            if op.path == "/api/v1/payments" and op.method == "POST":
                payments_op = op
                break

        assert payments_op is not None
        result = await dispatcher.dispatch(
            mock_client, payments_op, {"amount": 100, "out": False}
        )
        parsed = json.loads(result)
        assert "qrcode" in parsed["qr_code"]
        assert parsed["lightning_uri"].startswith("lightning:")

    @pytest.mark.asyncio
    async def test_outgoing_payment_no_qr_code(self, registry):
        """Outgoing payments should not include qr_code or lightning_uri."""
        dispatcher = Dispatcher()
        mock_client = AsyncMock()
        mock_client._request = AsyncMock(
            return_value={"payment_hash": "abc123", "checking_id": "xyz"}
        )
        mock_client.config = LNbitsConfig(lnbits_url="http://localhost:5000")

        payments_op = None
        for name, op in registry._operations.items():
            if op.path == "/api/v1/payments" and op.method == "POST":
                payments_op = op
                break

        assert payments_op is not None
        result = await dispatcher.dispatch(
            mock_client, payments_op, {"amount": 100, "out": True, "bolt11": "lnbc..."}
        )
        parsed = json.loads(result)
        assert "qr_code" not in parsed
        assert "lightning_uri" not in parsed

    @pytest.mark.asyncio
    async def test_access_token_injected_on_user_level_endpoint(self, registry):
        """Dispatching to an endpoint with usr param should inject Bearer token."""
        dispatcher = Dispatcher()
        mock_client = AsyncMock()
        mock_client._request = AsyncMock(return_value=[{"id": "w1"}])
        mock_client.config = LNbitsConfig(lnbits_url="http://localhost:5000")

        wallets_op = None
        for name, op in registry._operations.items():
            if op.path == "/api/v1/wallets" and op.method == "GET":
                wallets_op = op
                break

        assert wallets_op is not None
        await dispatcher.dispatch(
            mock_client, wallets_op, {}, access_token="test-jwt-token-123"
        )
        mock_client._request.assert_called_once()
        call_kwargs = mock_client._request.call_args
        assert call_kwargs.kwargs.get("headers") == {
            "Authorization": "Bearer test-jwt-token-123"
        }

    @pytest.mark.asyncio
    async def test_configure_lnbits_roundtrip(self, config_manager):
        """configure_lnbits then get_configuration should reflect changes."""
        meta = MetaTools(config_manager)
        meta.set_callbacks(
            refresh_fn=AsyncMock(return_value=5),
            get_extensions_fn=lambda: {},
        )

        result = await meta.call_tool(
            "configure_lnbits",
            {"lnbits_url": "http://newhost:5000", "api_key": "newkey123"},
        )
        parsed = json.loads(result)
        assert parsed["success"] is True

        result = await meta.call_tool("get_configuration", {})
        parsed = json.loads(result)
        assert "newhost" in parsed["config"]["lnbits_url"]
        assert parsed["config"]["api_key"] == "***MASKED***"

    def test_curated_description_for_payments(self, registry):
        """payments_create_payments should have a curated description mentioning qr_code."""
        tools = registry.get_mcp_tools()
        payments_tool = None
        for t in tools:
            if t.name == "payments_create_payments":
                payments_tool = t
                break

        assert payments_tool is not None
        assert "qr_code" in payments_tool.description
