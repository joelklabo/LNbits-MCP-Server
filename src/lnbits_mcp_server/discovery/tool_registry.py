"""Tool registry: filters discovered operations and converts them to MCP Tools."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

import structlog
from mcp.types import Tool

from .curated_descriptions import CURATED_DESCRIPTIONS, SKIP_TAGS
from .openapi_parser import DiscoveredOperation

logger = structlog.get_logger(__name__)


@dataclass
class RegistryConfig:
    """Filtering / safety knobs for the tool registry."""

    exclude_methods: list[str] = field(default_factory=lambda: ["DELETE"])
    exclude_paths: list[str] = field(
        default_factory=lambda: [
            "/docs",
            "/openapi.json",
            "/redoc",
        ]
    )
    include_extensions: list[str] | None = None  # None = all
    exclude_extensions: list[str] | None = None
    max_tools: int = 200


class ToolRegistry:
    """Stores discovered operations and converts them to MCP Tool objects."""

    def __init__(self, config: RegistryConfig | None = None):
        self.config = config or RegistryConfig()
        self._operations: dict[str, DiscoveredOperation] = {}
        self.last_refresh: float = 0.0

    # ------------------------------------------------------------------
    # Bulk load
    # ------------------------------------------------------------------

    def load(self, operations: list[DiscoveredOperation]) -> int:
        """Filter *operations* and store them. Returns count of accepted tools."""
        self._operations.clear()
        accepted = 0
        for op in operations:
            if self._should_skip(op):
                continue
            self._operations[op.tool_name] = op
            accepted += 1
            if accepted >= self.config.max_tools:
                logger.warning("Max tools reached", max_tools=self.config.max_tools)
                break

        self.last_refresh = time.time()
        logger.info("Tool registry loaded", tool_count=accepted)
        return accepted

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def get(self, tool_name: str) -> DiscoveredOperation | None:
        return self._operations.get(tool_name)

    @property
    def tool_names(self) -> list[str]:
        return list(self._operations)

    @property
    def tool_count(self) -> int:
        return len(self._operations)

    def get_extensions(self) -> dict[str, int]:
        """Return {extension_name: tool_count} for discovered extensions."""
        ext_counts: dict[str, int] = {}
        for op in self._operations.values():
            name = op.extension_name or "core"
            ext_counts[name] = ext_counts.get(name, 0) + 1
        return dict(sorted(ext_counts.items()))

    # ------------------------------------------------------------------
    # MCP conversion
    # ------------------------------------------------------------------

    def get_mcp_tools(self) -> list[Tool]:
        """Convert all registered operations to MCP Tool objects."""
        tools: list[Tool] = []
        for op in self._operations.values():
            tools.append(self._to_mcp_tool(op))
        return tools

    def _to_mcp_tool(self, op: DiscoveredOperation) -> Tool:
        description = CURATED_DESCRIPTIONS.get(
            op.tool_name, op.summary or op.description
        )
        input_schema = self._build_input_schema(op)
        return Tool(
            name=op.tool_name,
            description=description,
            inputSchema=input_schema,
        )

    # ------------------------------------------------------------------
    # Schema sanitization
    # ------------------------------------------------------------------

    # JSON Schema keywords allowed in draft 2020-12 input schemas.
    _ALLOWED_KEYWORDS: set[str] = {
        "type",
        "properties",
        "required",
        "items",
        "enum",
        "anyOf",
        "oneOf",
        "allOf",
        "minimum",
        "maximum",
        "exclusiveMinimum",
        "exclusiveMaximum",
        "pattern",
        "format",
        "description",
        "default",
        "additionalProperties",
        "minItems",
        "maxItems",
        "minLength",
        "maxLength",
        "const",
        "prefixItems",
        "$ref",
    }

    # Numeric keywords where float values like 1.0 should be coerced to int.
    _NUMERIC_KEYWORDS: set[str] = {
        "minimum",
        "maximum",
        "exclusiveMinimum",
        "exclusiveMaximum",
        "minItems",
        "maxItems",
        "minLength",
        "maxLength",
    }

    @classmethod
    def _sanitize_schema(cls, schema: dict[str, Any]) -> dict[str, Any]:
        """Recursively strip OpenAPI-only keywords from a schema dict.

        Also converts ``nullable: true`` into a JSON Schema ``anyOf`` with
        ``{"type": "null"}``, and coerces whole-number floats (e.g. ``1.0``)
        to ``int`` in numeric constraint keywords.
        """
        result: dict[str, Any] = {}

        # Handle nullable → anyOf conversion
        is_nullable = schema.get("nullable", False)

        for key, value in schema.items():
            if key not in cls._ALLOWED_KEYWORDS:
                continue
            if key == "properties" and isinstance(value, dict):
                result["properties"] = {
                    k: cls._sanitize_schema(v) if isinstance(v, dict) else v
                    for k, v in value.items()
                }
            elif key == "items" and isinstance(value, dict):
                result["items"] = cls._sanitize_schema(value)
            elif key in ("anyOf", "oneOf", "allOf") and isinstance(value, list):
                result[key] = [
                    cls._sanitize_schema(v) if isinstance(v, dict) else v
                    for v in value
                ]
            elif key == "additionalProperties" and isinstance(value, dict):
                result[key] = cls._sanitize_schema(value)
            elif key in cls._NUMERIC_KEYWORDS and isinstance(value, float):
                result[key] = int(value) if value == int(value) else value
            else:
                result[key] = value

        # Convert nullable to anyOf
        if is_nullable and "type" in result:
            original_type = result.pop("type")
            result["anyOf"] = [{"type": original_type}, {"type": "null"}]

        # Ensure sub-schemas have type info (enum-only schemas need "type": "string")
        if result and not any(
            k in result for k in ("type", "anyOf", "oneOf", "allOf", "$ref")
        ):
            if "enum" in result or "description" in result:
                result["type"] = "string"

        return result

    # ------------------------------------------------------------------
    # Input schema builder
    # ------------------------------------------------------------------

    @classmethod
    def _build_input_schema(cls, op: DiscoveredOperation) -> dict[str, Any]:
        """Build a JSON Schema ``inputSchema`` from path/query params + body."""
        properties: dict[str, Any] = {}
        required: list[str] = []

        # Names to hide from tool schemas (auto-injected or irrelevant)
        hidden_params = {"usr", "cookie_access_token"}

        # Path + query parameters
        for param in op.parameters:
            name = param.get("name", "")
            if name in hidden_params:
                continue
            if param.get("in") == "cookie":
                continue
            schema = param.get("schema", {"type": "string"})
            prop = cls._extract_prop(schema)
            properties[name] = prop
            if param.get("required", False):
                required.append(name)

        # Request body properties
        if op.request_body_schema:
            body = op.request_body_schema
            body_props = body.get("properties", {})
            body_required = body.get("required", [])
            for prop_name, prop_schema in body_props.items():
                prop = cls._extract_prop(prop_schema)
                properties[prop_name] = prop
                if prop_name in body_required:
                    required.append(prop_name)

        result: dict[str, Any] = {
            "type": "object",
            "properties": properties,
        }
        if required:
            result["required"] = required
        return result

    @classmethod
    def _extract_prop(cls, schema: dict[str, Any]) -> dict[str, Any]:
        """Extract a single property schema, sanitized for JSON Schema 2020-12."""
        # Convert OpenAPI "title" to "description" if no description exists
        prepared = dict(schema)
        if "description" not in prepared and "title" in prepared:
            prepared["description"] = prepared.pop("title")
        result = cls._sanitize_schema(prepared)
        # Ensure every property has a type (or anyOf/oneOf/allOf/enum)
        has_type_info = any(
            k in result for k in ("type", "anyOf", "oneOf", "allOf", "enum", "$ref")
        )
        if not has_type_info:
            result["type"] = "string"
        return result

    # ------------------------------------------------------------------
    # Filtering
    # ------------------------------------------------------------------

    def _should_skip(self, op: DiscoveredOperation) -> bool:
        # Skip by tag
        if op.tag in SKIP_TAGS:
            return True

        # Skip by HTTP method
        if op.method.upper() in (m.upper() for m in self.config.exclude_methods):
            return True

        # Skip by path prefix
        for prefix in self.config.exclude_paths:
            if op.path.startswith(prefix):
                return True

        # Skip non-API paths (HTML pages served by extensions)
        if "/api/" not in op.path:
            return True

        # Extension whitelist/blacklist
        if op.extension_name:
            if (
                self.config.include_extensions is not None
                and op.extension_name not in self.config.include_extensions
            ):
                return True
            if (
                self.config.exclude_extensions is not None
                and op.extension_name in self.config.exclude_extensions
            ):
                return True

        return False
