"""Tests for discovery.tool_registry."""

import pytest
from mcp.types import Tool

from lnbits_mcp_server.discovery.openapi_parser import (
    DiscoveredOperation,
    OpenAPIParser,
)
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
        assert "core" in exts or any(v > 0 for k, v in exts.items() if k != "lnurlp")

    def test_include_extensions_filter(self, operations):
        reg = ToolRegistry(RegistryConfig(include_extensions=["lnurlp"]))
        reg.load(operations)
        for op in reg._operations.values():
            if op.extension_name is not None:
                assert op.extension_name == "lnurlp"

    def test_exclude_extensions_filter(self, operations):
        reg = ToolRegistry(
            RegistryConfig(exclude_extensions=["lnurlp"], exclude_methods=[])
        )
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
        from lnbits_mcp_server.discovery.curated_descriptions import (
            CURATED_DESCRIPTIONS,
        )

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
                {
                    "name": "usr",
                    "in": "query",
                    "required": True,
                    "schema": {"type": "string"},
                },
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
                {
                    "name": "cookie_access_token",
                    "in": "cookie",
                    "schema": {"type": "string"},
                },
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

    def test_openapi_keywords_stripped_from_params(self):
        """OpenAPI-only keywords like nullable, example, etc. must be stripped."""
        op = DiscoveredOperation(
            tool_name="test_tool",
            method="GET",
            path="/api/v1/payments",
            summary="Get payments",
            description="Get payments",
            tag="payments",
            parameters=[
                {
                    "name": "checking_id",
                    "in": "query",
                    "schema": {
                        "type": "string",
                        "nullable": True,
                        "example": "abc123",
                        "deprecated": True,
                        "description": "The checking ID",
                    },
                },
            ],
            request_body_schema=None,
            security_schemes=[],
            is_public=False,
            extension_name=None,
        )
        schema = ToolRegistry._build_input_schema(op)
        prop = schema["properties"]["checking_id"]
        assert "nullable" not in prop
        assert "example" not in prop
        assert "deprecated" not in prop
        assert prop["description"] == "The checking ID"
        # nullable should be converted to anyOf
        assert "anyOf" in prop
        assert {"type": "null"} in prop["anyOf"]

    def test_items_sanitized_recursively(self):
        """items sub-schemas must also be sanitized."""
        op = DiscoveredOperation(
            tool_name="test_tool",
            method="POST",
            path="/api/v1/payments",
            summary="Create payment",
            description="Create payment",
            tag="payments",
            parameters=[],
            request_body_schema={
                "properties": {
                    "tags": {
                        "type": "array",
                        "items": {
                            "type": "string",
                            "example": "tag1",
                            "nullable": True,
                            "readOnly": True,
                        },
                    }
                },
                "required": [],
            },
            security_schemes=[],
            is_public=False,
            extension_name=None,
        )
        schema = ToolRegistry._build_input_schema(op)
        items = schema["properties"]["tags"]["items"]
        assert "example" not in items
        assert "readOnly" not in items
        assert "nullable" not in items
        # nullable converted to anyOf
        assert "anyOf" in items

    def test_nested_properties_sanitized(self):
        """Deeply nested schemas must be sanitized."""
        op = DiscoveredOperation(
            tool_name="test_tool",
            method="POST",
            path="/api/v1/payments",
            summary="Create",
            description="Create",
            tag="payments",
            parameters=[],
            request_body_schema={
                "properties": {
                    "extra": {
                        "type": "object",
                        "properties": {
                            "inner": {
                                "type": "string",
                                "example": "foo",
                                "xml": {"wrapped": True},
                            }
                        },
                    }
                },
                "required": [],
            },
            security_schemes=[],
            is_public=False,
            extension_name=None,
        )
        schema = ToolRegistry._build_input_schema(op)
        inner = schema["properties"]["extra"]["properties"]["inner"]
        assert "example" not in inner
        assert "xml" not in inner
        assert inner["type"] == "string"

    # ------------------------------------------------------------------
    # Integration: no OpenAPI keywords leak through any tool schema
    # ------------------------------------------------------------------

    # OpenAPI-only keywords that must never appear in MCP inputSchemas.
    OPENAPI_ONLY_KEYWORDS = {
        "nullable",
        "example",
        "examples",
        "deprecated",
        "readOnly",
        "writeOnly",
        "discriminator",
        "xml",
        "externalDocs",
    }

    @classmethod
    def _collect_keys_recursive(cls, obj, collected=None):
        """Walk a JSON-like structure and collect every dict key."""
        if collected is None:
            collected = set()
        if isinstance(obj, dict):
            for key, value in obj.items():
                collected.add(key)
                cls._collect_keys_recursive(value, collected)
        elif isinstance(obj, list):
            for item in obj:
                cls._collect_keys_recursive(item, collected)
        return collected

    def test_no_openapi_keywords_in_any_tool_schema(self, operations):
        """Every tool schema from the real fixture must be free of OpenAPI-only keywords."""
        reg = ToolRegistry(RegistryConfig(exclude_methods=[]))
        reg.load(operations)
        tools = reg.get_mcp_tools()
        assert len(tools) > 0, "Expected at least one tool"

        for tool in tools:
            keys = self._collect_keys_recursive(tool.inputSchema)
            leaked = keys & self.OPENAPI_ONLY_KEYWORDS
            assert not leaked, (
                f"Tool '{tool.name}' has OpenAPI-only keywords in its "
                f"inputSchema: {leaked}"
            )

    def test_nullable_converted_to_anyof_in_fixture_tools(self, operations):
        """Params with nullable:true in the fixture must produce anyOf with null type."""
        reg = ToolRegistry(RegistryConfig(exclude_methods=[]))
        reg.load(operations)
        tools = reg.get_mcp_tools()
        tool_map = {t.name: t for t in tools}

        # GET /api/v1/payments → payments_list_payments has checking_id with nullable
        tool = tool_map.get("payments_list_payments")
        assert tool is not None, "Expected payments_list_payments tool"
        prop = tool.inputSchema["properties"]["checking_id"]
        assert "nullable" not in prop
        assert "anyOf" in prop
        assert {"type": "null"} in prop["anyOf"]

    # ------------------------------------------------------------------
    # _sanitize_schema unit tests
    # ------------------------------------------------------------------

    def test_sanitize_schema_preserves_allowed_keywords(self):
        """Allowed JSON Schema keywords must pass through."""
        schema = {
            "type": "string",
            "description": "A name",
            "minLength": 1,
            "maxLength": 100,
            "pattern": "^[a-z]+$",
            "format": "email",
            "default": "test",
            "enum": ["a", "b"],
        }
        result = ToolRegistry._sanitize_schema(schema)
        for key in schema:
            assert key in result, f"Allowed keyword '{key}' was stripped"
        assert result == schema

    def test_sanitize_schema_strips_all_openapi_keywords(self):
        """Every known OpenAPI-only keyword must be stripped."""
        schema = {
            "type": "string",
            "nullable": True,
            "example": "foo",
            "examples": ["foo", "bar"],
            "deprecated": True,
            "readOnly": True,
            "writeOnly": False,
            "discriminator": {"propertyName": "type"},
            "xml": {"name": "item"},
            "externalDocs": {"url": "https://example.com"},
        }
        result = ToolRegistry._sanitize_schema(schema)
        for kw in self.OPENAPI_ONLY_KEYWORDS:
            assert kw not in result, f"OpenAPI keyword '{kw}' was not stripped"

    def test_sanitize_schema_anyof_members_sanitized(self):
        """anyOf/oneOf/allOf members must be recursively sanitized."""
        schema = {
            "anyOf": [
                {"type": "string", "example": "foo"},
                {"type": "integer", "deprecated": True},
            ]
        }
        result = ToolRegistry._sanitize_schema(schema)
        assert len(result["anyOf"]) == 2
        assert result["anyOf"][0] == {"type": "string"}
        assert result["anyOf"][1] == {"type": "integer"}

    def test_sanitize_schema_empty_input(self):
        """Empty schema should return empty dict."""
        assert ToolRegistry._sanitize_schema({}) == {}

    def test_sanitize_schema_only_forbidden_keys(self):
        """Schema with only OpenAPI keywords should return empty dict."""
        schema = {"example": "foo", "deprecated": True, "xml": {"name": "x"}}
        assert ToolRegistry._sanitize_schema(schema) == {}

    def test_title_to_description_fallback(self):
        """_extract_prop should convert title to description when no description."""
        schema = {"type": "string", "title": "My Title"}
        result = ToolRegistry._extract_prop(schema)
        assert result["description"] == "My Title"
        assert "title" not in result

    def test_title_not_override_description(self):
        """_extract_prop should keep description when both title and description exist."""
        schema = {"type": "string", "title": "Title", "description": "Desc"}
        result = ToolRegistry._extract_prop(schema)
        assert result["description"] == "Desc"
        assert "title" not in result

    def test_extract_prop_empty_schema_defaults_to_string(self):
        """_extract_prop with only forbidden keys should fall back to {type: string}."""
        schema = {"example": "foo", "deprecated": True}
        result = ToolRegistry._extract_prop(schema)
        assert result == {"type": "string"}
