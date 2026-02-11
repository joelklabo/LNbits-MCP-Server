"""Tests for discovery.openapi_parser."""

import pytest

from lnbits_mcp_server.discovery.openapi_parser import (
    DiscoveredOperation,
    OpenAPIParser,
    _slugify,
)


@pytest.fixture
def parser():
    return OpenAPIParser("http://localhost:5000")


class TestSlugify:
    def test_basic(self):
        assert _slugify("Wallet") == "wallet"

    def test_spaces_and_special(self):
        assert _slugify("Admin UI") == "admin_ui"
        assert _slugify("Extension Managment") == "extension_managment"

    def test_leading_trailing(self):
        assert _slugify("  hello!  ") == "hello"


class TestParseSpec:
    def test_parses_operations(self, parser, openapi_spec):
        ops = parser.parse_spec_dict(openapi_spec)
        assert len(ops) > 0
        assert all(isinstance(op, DiscoveredOperation) for op in ops)

    def test_tool_names_unique(self, parser, openapi_spec):
        ops = parser.parse_spec_dict(openapi_spec)
        names = [op.tool_name for op in ops]
        assert len(names) == len(set(names)), f"Duplicate names: {names}"

    def test_extension_detection(self, parser, openapi_spec):
        ops = parser.parse_spec_dict(openapi_spec)
        lnurlp_ops = [op for op in ops if op.extension_name == "lnurlp"]
        assert len(lnurlp_ops) > 0

        core_ops = [op for op in ops if op.extension_name is None]
        assert len(core_ops) > 0

    def test_ref_resolution(self, parser, openapi_spec):
        ops = parser.parse_spec_dict(openapi_spec)
        # The payments POST uses $ref to CreateInvoiceData
        payments_create = [
            op for op in ops if op.path == "/api/v1/payments" and op.method == "POST"
        ]
        assert len(payments_create) == 1
        body = payments_create[0].request_body_schema
        assert body is not None
        assert "properties" in body
        assert "amount" in body["properties"]

    def test_parameters_extracted(self, parser, openapi_spec):
        ops = parser.parse_spec_dict(openapi_spec)
        # GET /api/v1/payments has a `limit` query param
        payments_list = [
            op for op in ops if op.path == "/api/v1/payments" and op.method == "GET"
        ]
        assert len(payments_list) == 1
        param_names = [p["name"] for p in payments_list[0].parameters]
        assert "limit" in param_names

    def test_security_extracted(self, parser, openapi_spec):
        ops = parser.parse_spec_dict(openapi_spec)
        wallet_get = [
            op for op in ops if op.path == "/api/v1/wallet" and op.method == "GET"
        ]
        assert len(wallet_get) == 1
        assert "APIKeyHeader" in wallet_get[0].security_schemes
        assert not wallet_get[0].is_public

    def test_public_endpoint(self, parser, openapi_spec):
        ops = parser.parse_spec_dict(openapi_spec)
        health = [op for op in ops if op.path == "/api/v1/health"]
        assert len(health) == 1
        assert health[0].is_public

    def test_method_parsing(self, parser, openapi_spec):
        ops = parser.parse_spec_dict(openapi_spec)
        methods = {op.method for op in ops}
        assert "GET" in methods
        assert "POST" in methods
        assert "PUT" in methods
        assert "DELETE" in methods


class TestBuildToolName:
    def test_basic(self):
        name = OpenAPIParser._build_tool_name("Wallet", "get", "/api/v1/wallet")
        assert name == "wallet_get_wallet"

    def test_list_endpoint(self):
        name = OpenAPIParser._build_tool_name("Payments", "get", "/api/v1/payments")
        assert name == "payments_list_payments"

    def test_with_path_param(self):
        name = OpenAPIParser._build_tool_name(
            "Payments", "get", "/api/v1/payments/{payment_hash}"
        )
        assert "payments" in name

    def test_extension_path(self):
        name = OpenAPIParser._build_tool_name(
            "lnurlp", "get", "/lnurlp/api/v1/links"
        )
        assert name == "lnurlp_list_links"
