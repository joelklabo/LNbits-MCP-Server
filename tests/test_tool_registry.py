"""Tests for discovery.tool_registry."""

import pytest
from mcp.types import Tool

from lnbits_mcp_server.discovery.openapi_parser import DiscoveredOperation, OpenAPIParser
from lnbits_mcp_server.discovery.tool_registry import RegistryConfig, ToolRegistry


@pytest.fixture
def operations(openapi_spec):
    parser = OpenAPIParser("http://localhost:5000")
    return parser.parse_spec_dict(openapi_spec)


class TestToolRegistry:
    def test_load_filters_deletes(self, operations):
        reg = ToolRegistry()
        count = reg.load(operations)
        # DELETE operations should be filtered out by default
        for op in reg._operations.values():
            assert op.method != "DELETE"

    def test_load_filters_non_api_paths(self, operations):
        reg = ToolRegistry()
        reg.load(operations)
        # HTML page paths like /lnurlp/ should be excluded
        for op in reg._operations.values():
            assert "/api/" in op.path

    def test_max_tools_cap(self, operations):
        reg = ToolRegistry(RegistryConfig(max_tools=3, exclude_methods=[]))
        count = reg.load(operations)
        assert count <= 3
        assert reg.tool_count <= 3

    def test_get_mcp_tools(self, operations):
        reg = ToolRegistry()
        reg.load(operations)
        tools = reg.get_mcp_tools()
        assert len(tools) > 0
        assert all(isinstance(t, Tool) for t in tools)
        for t in tools:
            assert t.name
            assert t.description
            assert t.inputSchema

    def test_get_extensions(self, operations):
        reg = ToolRegistry(RegistryConfig(exclude_methods=[]))
        reg.load(operations)
        exts = reg.get_extensions()
        assert "lnurlp" in exts
        assert "core" in exts or any(
            v > 0 for k, v in exts.items() if k != "lnurlp"
        )

    def test_include_extensions_filter(self, operations):
        reg = ToolRegistry(RegistryConfig(include_extensions=["lnurlp"]))
        reg.load(operations)
        for op in reg._operations.values():
            if op.extension_name is not None:
                assert op.extension_name == "lnurlp"

    def test_exclude_extensions_filter(self, operations):
        reg = ToolRegistry(RegistryConfig(exclude_extensions=["lnurlp"], exclude_methods=[]))
        reg.load(operations)
        for op in reg._operations.values():
            assert op.extension_name != "lnurlp"

    def test_input_schema_has_required(self, operations):
        reg = ToolRegistry(RegistryConfig(exclude_methods=[]))
        reg.load(operations)
        tools = reg.get_mcp_tools()
        # At least one tool should have required fields
        has_required = any(
            "required" in t.inputSchema and len(t.inputSchema["required"]) > 0
            for t in tools
        )
        assert has_required

    def test_curated_description_applied(self, operations):
        """If a curated description key matches, it should override the summary."""
        reg = ToolRegistry()
        reg.load(operations)
        tools = reg.get_mcp_tools()
        tool_map = {t.name: t for t in tools}
        # Check if any curated description was applied
        from lnbits_mcp_server.discovery.curated_descriptions import CURATED_DESCRIPTIONS
        for name, desc in CURATED_DESCRIPTIONS.items():
            if name in tool_map:
                assert tool_map[name].description == desc
                break

    def test_last_refresh_updated(self, operations):
        reg = ToolRegistry()
        assert reg.last_refresh == 0.0
        reg.load(operations)
        assert reg.last_refresh > 0

    def test_usr_hidden_from_schema(self):
        """usr param should be hidden since it's auto-injected."""
        op = DiscoveredOperation(
            tool_name="test_tool",
            method="GET",
            path="/api/v1/wallets",
            summary="List wallets",
            description="List wallets",
            tag="core",
            parameters=[
                {"name": "usr", "in": "query", "required": True, "schema": {"type": "string"}},
                {"name": "limit", "in": "query", "schema": {"type": "integer"}},
            ],
            request_body_schema=None,
            security_schemes=[],
            is_public=False,
            extension_name=None,
        )
        schema = ToolRegistry._build_input_schema(op)
        assert "usr" not in schema["properties"]
        assert "limit" in schema["properties"]
        # usr should not appear in required either
        assert "usr" not in schema.get("required", [])

    def test_cookie_param_hidden_from_schema(self):
        """Cookie params like cookie_access_token should be hidden."""
        op = DiscoveredOperation(
            tool_name="test_tool",
            method="GET",
            path="/api/v1/auth",
            summary="Auth",
            description="Auth",
            tag="auth",
            parameters=[
                {"name": "cookie_access_token", "in": "cookie", "schema": {"type": "string"}},
                {"name": "limit", "in": "query", "schema": {"type": "integer"}},
            ],
            request_body_schema=None,
            security_schemes=[],
            is_public=False,
            extension_name=None,
        )
        schema = ToolRegistry._build_input_schema(op)
        assert "cookie_access_token" not in schema["properties"]
        assert "limit" in schema["properties"]
