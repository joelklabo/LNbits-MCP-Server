"""Curated infrastructure tools that are NOT auto-discovered."""

from __future__ import annotations

import json
from typing import Any

from mcp.types import Tool

from ..client import LNbitsClient, LNbitsError
from ..utils.runtime_config import RuntimeConfigManager

# ─── Tool definitions ────────────────────────────────────────────────

META_TOOL_DEFINITIONS: list[Tool] = [
    Tool(
        name="configure_lnbits",
        description="Configure LNbits connection parameters at runtime.",
        inputSchema={
            "type": "object",
            "properties": {
                "lnbits_url": {
                    "type": "string",
                    "description": "Base URL for LNbits instance (e.g. https://demo.lnbits.com)",
                },
                "api_key": {
                    "type": "string",
                    "description": "API key for LNbits authentication",
                },
                "bearer_token": {
                    "type": "string",
                    "description": "Bearer token for authentication (alternative to api_key)",
                },
                "oauth2_token": {
                    "type": "string",
                    "description": "OAuth2 token for authentication (alternative to api_key)",
                },
                "auth_method": {
                    "type": "string",
                    "description": "Authentication method",
                    "enum": [
                        "api_key_header",
                        "api_key_query",
                        "http_bearer",
                        "oauth2",
                    ],
                },
                "timeout": {
                    "type": "integer",
                    "description": "Request timeout in seconds",
                    "minimum": 1,
                    "maximum": 300,
                },
                "rate_limit_per_minute": {
                    "type": "integer",
                    "description": "Rate limit per minute",
                    "minimum": 1,
                    "maximum": 1000,
                },
            },
        },
    ),
    Tool(
        name="test_connection",
        description="Test the current LNbits connection by making a test API call.",
        inputSchema={"type": "object", "properties": {}},
    ),
    Tool(
        name="get_configuration",
        description="Show current LNbits configuration with masked API keys.",
        inputSchema={"type": "object", "properties": {}},
    ),
    Tool(
        name="refresh_tools",
        description=(
            "Re-fetch the OpenAPI spec from LNbits and rebuild the tool list. "
            "Use after enabling/disabling extensions."
        ),
        inputSchema={"type": "object", "properties": {}},
    ),
    Tool(
        name="list_extensions",
        description="Show all discovered extensions and their tool counts.",
        inputSchema={"type": "object", "properties": {}},
    ),
    Tool(
        name="pay_lightning_address",
        description=(
            "Send sats to a Lightning address (user@domain.com). "
            "Resolves the address via LNURL-pay, fetches an invoice, and pays it. "
            "Amount is in sats, NOT msats."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "lightning_address": {
                    "type": "string",
                    "description": "Lightning address (e.g. user@domain.com)",
                    "pattern": "^[^@]+@[^@]+\\.[^@]+$",
                },
                "amount_sats": {
                    "type": "integer",
                    "description": "Amount to pay in satoshis",
                    "minimum": 1,
                },
                "comment": {
                    "type": "string",
                    "description": "Optional comment for the payment",
                },
            },
            "required": ["lightning_address", "amount_sats"],
        },
    ),
]

META_TOOL_NAMES: set[str] = {t.name for t in META_TOOL_DEFINITIONS}


class MetaTools:
    """Handles the curated infrastructure tools."""

    def __init__(self, config_manager: RuntimeConfigManager):
        self._config_manager = config_manager
        # Populated by server after discovery
        self._get_extensions_fn: Any = None
        self._refresh_fn: Any = None

    def set_callbacks(
        self,
        *,
        refresh_fn: Any = None,
        get_extensions_fn: Any = None,
    ) -> None:
        """Set callbacks that the server provides after init."""
        self._refresh_fn = refresh_fn
        self._get_extensions_fn = get_extensions_fn

    @staticmethod
    def get_tools() -> list[Tool]:
        return list(META_TOOL_DEFINITIONS)

    async def call_tool(
        self, name: str, arguments: dict[str, Any]
    ) -> str:
        """Dispatch a meta tool call. Returns a text string."""
        if name == "configure_lnbits":
            return await self._configure(arguments)
        if name == "test_connection":
            return await self._test_connection()
        if name == "get_configuration":
            return self._get_configuration()
        if name == "refresh_tools":
            return await self._refresh_tools()
        if name == "list_extensions":
            return self._list_extensions()
        if name == "pay_lightning_address":
            return await self._pay_lightning_address(arguments)
        raise ValueError(f"Unknown meta tool: {name}")

    # ─── Handlers ──────────────────────────────────────────────────

    async def _configure(self, arguments: dict[str, Any]) -> str:
        result = await self._config_manager.update_configuration(**arguments)
        return json.dumps(result, indent=2, default=str)

    async def _test_connection(self) -> str:
        result = await self._config_manager.test_configuration()
        return json.dumps(result, indent=2, default=str)

    def _get_configuration(self) -> str:
        status = self._config_manager.get_configuration_status()
        return json.dumps(status, indent=2, default=str)

    async def _refresh_tools(self) -> str:
        if self._refresh_fn is None:
            return json.dumps({"error": "Refresh callback not set"})
        count = await self._refresh_fn()
        return json.dumps({
            "success": True,
            "message": f"Refreshed tool list — {count} tools discovered",
            "tool_count": count,
        })

    def _list_extensions(self) -> str:
        if self._get_extensions_fn is None:
            return json.dumps({"error": "Extension query callback not set"})
        extensions = self._get_extensions_fn()
        return json.dumps({
            "extensions": extensions,
            "total_extensions": len(extensions),
            "total_tools": sum(extensions.values()),
        }, indent=2)

    async def _pay_lightning_address(self, arguments: dict[str, Any]) -> str:
        address = arguments["lightning_address"]
        amount = arguments["amount_sats"]
        comment = arguments.get("comment")
        client = await self._config_manager.get_client()
        result = await client.pay_lightning_address(address, amount, comment)
        return json.dumps(result, indent=2, default=str)
