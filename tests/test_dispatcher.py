"""Tests for discovery.dispatcher."""

import json
from unittest.mock import AsyncMock, MagicMock, PropertyMock

import pytest

from lnbits_mcp_server.discovery.dispatcher import Dispatcher
from lnbits_mcp_server.discovery.openapi_parser import DiscoveredOperation


def _make_op(**overrides) -> DiscoveredOperation:
    defaults = dict(
        tool_name="test_tool",
        method="GET",
        path="/api/v1/test",
        summary="Test",
        description="Test op",
        tag="test",
        parameters=[],
        request_body_schema=None,
        security_schemes=["APIKeyHeader"],
        is_public=False,
        extension_name=None,
    )
    defaults.update(overrides)
    return DiscoveredOperation(**defaults)


@pytest.fixture
def dispatcher():
    return Dispatcher()


@pytest.fixture
def mock_client():
    client = AsyncMock()
    client._request = AsyncMock(return_value={"status": "ok"})
    return client


class TestPathSubstitution:
    def test_simple_substitution(self):
        result = Dispatcher._substitute_path_params(
            "/api/v1/payments/{payment_hash}",
            {"payment_hash": "abc123"},
        )
        assert result == "/api/v1/payments/abc123"

    def test_multiple_params(self):
        result = Dispatcher._substitute_path_params(
            "/api/v1/{org}/{repo}/{tag}",
            {"org": "lnbits", "repo": "ext", "tag": "v1"},
        )
        assert result == "/api/v1/lnbits/ext/v1"

    def test_missing_param_left_as_is(self):
        result = Dispatcher._substitute_path_params(
            "/api/v1/{missing}",
            {},
        )
        assert result == "/api/v1/{missing}"


class TestParamSeparation:
    def test_query_params(self):
        op = _make_op(
            parameters=[
                {"name": "limit", "in": "query", "schema": {"type": "integer"}},
                {"name": "offset", "in": "query", "schema": {"type": "integer"}},
            ]
        )
        query, body = Dispatcher._separate_params(op, {"limit": 10, "offset": 5})
        assert query == {"limit": 10, "offset": 5}
        assert body == {}

    def test_path_params_excluded(self):
        op = _make_op(
            path="/api/v1/payments/{payment_hash}",
            parameters=[
                {"name": "payment_hash", "in": "path", "schema": {"type": "string"}},
            ],
        )
        query, body = Dispatcher._separate_params(op, {"payment_hash": "abc123"})
        assert query == {}
        assert body == {}  # path params are excluded

    def test_body_params(self):
        op = _make_op(
            parameters=[
                {"name": "limit", "in": "query", "schema": {"type": "integer"}},
            ],
        )
        query, body = Dispatcher._separate_params(
            op, {"limit": 10, "amount": 100, "memo": "test"}
        )
        assert query == {"limit": 10}
        assert body == {"amount": 100, "memo": "test"}


class TestDispatch:
    @pytest.mark.asyncio
    async def test_get_request(self, dispatcher, mock_client):
        op = _make_op(method="GET", path="/api/v1/wallet")
        result = await dispatcher.dispatch(mock_client, op, {})
        mock_client._request.assert_called_once_with(
            method="GET",
            path="/api/v1/wallet",
            params=None,
            json=None,
            headers=None,
        )
        parsed = json.loads(result)
        assert parsed == {"status": "ok"}

    @pytest.mark.asyncio
    async def test_post_with_body(self, dispatcher, mock_client):
        op = _make_op(
            method="POST",
            path="/api/v1/payments",
            parameters=[],
        )
        result = await dispatcher.dispatch(
            mock_client, op, {"amount": 100, "memo": "test"}
        )
        mock_client._request.assert_called_once_with(
            method="POST",
            path="/api/v1/payments",
            params=None,
            json={"amount": 100, "memo": "test"},
            headers=None,
        )

    @pytest.mark.asyncio
    async def test_get_with_path_param(self, dispatcher, mock_client):
        op = _make_op(
            method="GET",
            path="/api/v1/payments/{payment_hash}",
            parameters=[
                {"name": "payment_hash", "in": "path", "schema": {"type": "string"}},
            ],
        )
        result = await dispatcher.dispatch(mock_client, op, {"payment_hash": "abc123"})
        mock_client._request.assert_called_once_with(
            method="GET",
            path="/api/v1/payments/abc123",
            params=None,
            json=None,
            headers=None,
        )

    @pytest.mark.asyncio
    async def test_error_propagation(self, dispatcher, mock_client):
        from lnbits_mcp_server.client import LNbitsError

        mock_client._request.side_effect = LNbitsError("Not found", 404)
        op = _make_op(method="GET", path="/api/v1/wallet")
        with pytest.raises(LNbitsError):
            await dispatcher.dispatch(mock_client, op, {})


class TestAccessTokenInjection:
    """Regression tests for auto-injecting Bearer token on user-level endpoints."""

    @pytest.mark.asyncio
    async def test_token_injected_when_op_has_usr_param(self, dispatcher, mock_client):
        op = _make_op(
            method="GET",
            path="/api/v1/wallets",
            parameters=[
                {"name": "usr", "in": "query", "schema": {"type": "string"}},
                {
                    "name": "cookie_access_token",
                    "in": "cookie",
                    "schema": {"type": "string"},
                },
            ],
        )
        await dispatcher.dispatch(mock_client, op, {}, access_token="my-jwt-token")
        mock_client._request.assert_called_once_with(
            method="GET",
            path="/api/v1/wallets",
            params=None,
            json=None,
            headers={"Authorization": "Bearer my-jwt-token"},
        )

    @pytest.mark.asyncio
    async def test_token_not_injected_when_op_has_no_user_params(
        self, dispatcher, mock_client
    ):
        op = _make_op(
            method="GET",
            path="/api/v1/wallet",
            parameters=[],
        )
        await dispatcher.dispatch(mock_client, op, {}, access_token="my-jwt-token")
        mock_client._request.assert_called_once_with(
            method="GET",
            path="/api/v1/wallet",
            params=None,
            json=None,
            headers=None,
        )

    @pytest.mark.asyncio
    async def test_token_not_injected_when_access_token_is_none(
        self, dispatcher, mock_client
    ):
        op = _make_op(
            method="GET",
            path="/api/v1/wallets",
            parameters=[
                {"name": "usr", "in": "query", "schema": {"type": "string"}},
            ],
        )
        await dispatcher.dispatch(mock_client, op, {}, access_token=None)
        mock_client._request.assert_called_once_with(
            method="GET",
            path="/api/v1/wallets",
            params=None,
            json=None,
            headers=None,
        )

    @pytest.mark.asyncio
    async def test_token_injected_for_cookie_access_token_param(
        self, dispatcher, mock_client
    ):
        op = _make_op(
            method="GET",
            path="/api/v1/wallet/paginated",
            parameters=[
                {
                    "name": "cookie_access_token",
                    "in": "cookie",
                    "schema": {"type": "string"},
                },
                {"name": "limit", "in": "query", "schema": {"type": "integer"}},
            ],
        )
        await dispatcher.dispatch(
            mock_client, op, {"limit": 10}, access_token="my-jwt-token"
        )
        mock_client._request.assert_called_once_with(
            method="GET",
            path="/api/v1/wallet/paginated",
            params={"limit": 10},
            json=None,
            headers={"Authorization": "Bearer my-jwt-token"},
        )


class TestInvoiceEnrichment:
    """Tests for QR code and lightning URI enrichment on invoice creation."""

    def _mock_client_with_url(self, url="https://lnbits.example.com"):
        client = AsyncMock()
        config = MagicMock()
        config.lnbits_url = url
        client.config = config
        return client

    def test_invoice_response_gets_qr_code_and_lightning_uri(self):
        client = self._mock_client_with_url()
        op = _make_op(tool_name="payments_create_payments")
        result = {
            "payment_hash": "abc123",
            "payment_request": "lnbc100n1p0abcdef",
        }
        enriched = Dispatcher._enrich_invoice(result, op, {"out": False}, client)
        assert (
            enriched["qr_code"]
            == "https://lnbits.example.com/api/v1/qrcode/lnbc100n1p0abcdef"
        )
        assert enriched["lightning_uri"] == "lightning:lnbc100n1p0abcdef"

    def test_outgoing_payment_not_enriched(self):
        client = self._mock_client_with_url()
        op = _make_op(tool_name="payments_create_payments")
        result = {"payment_hash": "abc123", "payment_request": "lnbc100n1p0abcdef"}
        enriched = Dispatcher._enrich_invoice(result, op, {"out": True}, client)
        assert "qr_code" not in enriched
        assert "lightning_uri" not in enriched

    def test_non_payment_op_not_enriched(self):
        client = self._mock_client_with_url()
        op = _make_op(tool_name="wallet_get_wallet")
        result = {"id": "wallet1", "balance": 1000}
        enriched = Dispatcher._enrich_invoice(result, op, {}, client)
        assert "qr_code" not in enriched

    def test_uses_bolt11_field_as_fallback(self):
        client = self._mock_client_with_url()
        op = _make_op(tool_name="payments_create_payments")
        result = {"payment_hash": "abc123", "bolt11": "lnbc200n1p0xyz"}
        enriched = Dispatcher._enrich_invoice(result, op, {}, client)
        assert (
            enriched["qr_code"]
            == "https://lnbits.example.com/api/v1/qrcode/lnbc200n1p0xyz"
        )
        assert enriched["lightning_uri"] == "lightning:lnbc200n1p0xyz"

    def test_trailing_slash_url_handled(self):
        client = self._mock_client_with_url("https://lnbits.example.com/")
        op = _make_op(tool_name="payments_create_payments")
        result = {"payment_request": "lnbc100n1p0abcdef"}
        enriched = Dispatcher._enrich_invoice(result, op, {}, client)
        assert (
            enriched["qr_code"]
            == "https://lnbits.example.com/api/v1/qrcode/lnbc100n1p0abcdef"
        )
