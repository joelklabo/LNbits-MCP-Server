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
    # Input schema builder
    # ------------------------------------------------------------------

    @staticmethod
    def _build_input_schema(op: DiscoveredOperation) -> dict[str, Any]:
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
            # Clean schema for MCP (remove title, default handling)
            prop: dict[str, Any] = {}
            if "type" in schema:
                prop["type"] = schema["type"]
            if "enum" in schema:
                prop["enum"] = schema["enum"]
            if "description" in schema:
                prop["description"] = schema["description"]
            elif "title" in schema:
                prop["description"] = schema["title"]
            if "default" in schema:
                prop["default"] = schema["default"]
            if "items" in schema:
                prop["items"] = schema["items"]

            properties[name] = prop
            if param.get("required", False):
                required.append(name)

        # Request body properties
        if op.request_body_schema:
            body = op.request_body_schema
            body_props = body.get("properties", {})
            body_required = body.get("required", [])
            for prop_name, prop_schema in body_props.items():
                prop: dict[str, Any] = {}
                if "type" in prop_schema:
                    prop["type"] = prop_schema["type"]
                if "enum" in prop_schema:
                    prop["enum"] = prop_schema["enum"]
                if "description" in prop_schema:
                    prop["description"] = prop_schema["description"]
                elif "title" in prop_schema:
                    prop["description"] = prop_schema["title"]
                if "default" in prop_schema:
                    prop["default"] = prop_schema["default"]
                if "items" in prop_schema:
                    prop["items"] = prop_schema["items"]
                # Fallback: if no type info at all, default to string
                if not prop:
                    prop = {"type": "string"}

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
