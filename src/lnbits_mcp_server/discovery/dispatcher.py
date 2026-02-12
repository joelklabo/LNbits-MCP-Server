"""Generic HTTP dispatcher for discovered operations."""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import quote, urljoin

import structlog

from ..client import LNbitsClient
from .openapi_parser import DiscoveredOperation

logger = structlog.get_logger(__name__)


class Dispatcher:
    """Execute any DiscoveredOperation against the LNbits API."""

    # Parameter names that signal user-level auth is needed
    _USER_AUTH_PARAMS = {"usr", "cookie_access_token"}

    async def dispatch(
        self,
        client: LNbitsClient,
        op: DiscoveredOperation,
        arguments: dict[str, Any],
        *,
        access_token: str | None = None,
    ) -> str:
        """Build the HTTP request from *op* + *arguments* and return the
        JSON response body as a string (LLMs handle JSON well)."""

        path = self._substitute_path_params(op.path, arguments)
        query_params, body = self._separate_params(op, arguments)

        # Auto-inject Bearer token for endpoints that need user-level auth
        extra_headers: dict[str, str] = {}
        if access_token and self._needs_user_auth(op):
            extra_headers["Authorization"] = f"Bearer {access_token}"

        logger.info(
            "Dispatching",
            tool=op.tool_name,
            method=op.method,
            path=path,
        )

        result = await client._request(
            method=op.method,
            path=path,
            params=query_params or None,
            json=body or None,
            headers=extra_headers or None,
        )

        result = self._enrich_invoice(result, op, arguments, client)

        return json.dumps(result, indent=2, default=str)

    # ------------------------------------------------------------------
    # Post-processing
    # ------------------------------------------------------------------

    @staticmethod
    def _enrich_invoice(
        result: Any,
        op: DiscoveredOperation,
        arguments: dict[str, Any],
        client: LNbitsClient,
    ) -> Any:
        """Add QR code URL and lightning URI to invoice creation responses."""
        if op.tool_name != "payments_create_payments":
            return result
        # Only enrich invoice creation (out=false), not outgoing payments
        if arguments.get("out", False):
            return result
        if not isinstance(result, dict):
            return result

        bolt11 = result.get("payment_request") or result.get("bolt11")
        if not bolt11:
            return result

        base_url = str(client.config.lnbits_url).rstrip("/")
        result["qr_code"] = f"{base_url}/api/v1/qrcode/{quote(bolt11, safe='')}"
        result["lightning_uri"] = f"lightning:{bolt11}"
        return result

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @classmethod
    def _needs_user_auth(cls, op: DiscoveredOperation) -> bool:
        """Return True if the operation declares user-level auth parameters."""
        for p in op.parameters:
            if p.get("name") in cls._USER_AUTH_PARAMS:
                return True
        return False

    @staticmethod
    def _substitute_path_params(path_template: str, arguments: dict[str, Any]) -> str:
        """Replace ``{param}`` placeholders in the URL with actual values."""
        import re

        def _replacer(match: re.Match) -> str:
            key = match.group(1)
            if key in arguments:
                return str(arguments[key])
            return match.group(0)  # leave unreplaced if missing

        return re.sub(r"\{(\w+)\}", _replacer, path_template)

    @staticmethod
    def _separate_params(
        op: DiscoveredOperation,
        arguments: dict[str, Any],
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        """Split *arguments* into (query_params, body) based on OpenAPI
        parameter definitions."""

        # Build sets of known path and query parameter names
        path_params: set[str] = set()
        query_params_names: set[str] = set()
        for param in op.parameters:
            loc = param.get("in", "query")
            name = param.get("name", "")
            if loc == "path":
                path_params.add(name)
            elif loc == "query":
                query_params_names.add(name)

        query: dict[str, Any] = {}
        body: dict[str, Any] = {}

        for key, value in arguments.items():
            if key in path_params:
                continue  # already substituted
            if key in query_params_names:
                query[key] = value
            else:
                # Everything else goes into the request body
                body[key] = value

        return query, body
