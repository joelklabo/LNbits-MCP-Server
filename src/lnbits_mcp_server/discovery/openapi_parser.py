"""Fetch and parse the LNbits OpenAPI spec into DiscoveredOperation objects."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

import httpx
import structlog

logger = structlog.get_logger(__name__)

# HTTP method → default action verb
_METHOD_ACTIONS: dict[str, str] = {
    "get": "get",
    "post": "create",
    "put": "update",
    "patch": "update",
    "delete": "delete",
}


@dataclass
class DiscoveredOperation:
    """One API operation parsed from the OpenAPI spec."""

    tool_name: str
    method: str  # GET, POST, …
    path: str  # /lnurlp/api/v1/links
    summary: str
    description: str
    tag: str
    parameters: list[dict[str, Any]]
    request_body_schema: dict[str, Any] | None
    security_schemes: list[str]
    is_public: bool
    extension_name: str | None


class OpenAPIParser:
    """Fetches /openapi.json and converts it to DiscoveredOperation list."""

    def __init__(self, base_url: str, timeout: int = 15):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def fetch_and_parse(self) -> list[DiscoveredOperation]:
        """Fetch the OpenAPI spec from the LNbits instance and parse it."""
        spec = await self._fetch_spec()
        return self._parse_spec(spec)

    def parse_spec_dict(self, spec: dict[str, Any]) -> list[DiscoveredOperation]:
        """Parse an already-loaded spec dict (useful for testing)."""
        return self._parse_spec(spec)

    # ------------------------------------------------------------------
    # Fetch
    # ------------------------------------------------------------------

    async def _fetch_spec(self) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.get(f"{self.base_url}/openapi.json")
            resp.raise_for_status()
            return resp.json()

    # ------------------------------------------------------------------
    # Parse
    # ------------------------------------------------------------------

    def _parse_spec(self, spec: dict[str, Any]) -> list[DiscoveredOperation]:
        schemas = spec.get("components", {}).get("schemas", {})
        operations: list[DiscoveredOperation] = []
        seen_names: dict[str, int] = {}

        for path, path_item in spec.get("paths", {}).items():
            for method, op in path_item.items():
                if method not in _METHOD_ACTIONS:
                    continue

                tag = (op.get("tags") or ["other"])[0]
                summary = op.get("summary", "")
                description = op.get("description", summary)
                parameters = self._resolve_parameters(
                    op.get("parameters", []), schemas
                )
                body_schema = self._resolve_request_body(
                    op.get("requestBody"), schemas
                )
                security = self._extract_security(op.get("security", []))
                is_public = len(security) == 0
                extension = self._detect_extension(path)

                raw_name = self._build_tool_name(tag, method, path)
                # de-duplicate
                if raw_name in seen_names:
                    seen_names[raw_name] += 1
                    tool_name = f"{raw_name}_{seen_names[raw_name]}"
                else:
                    seen_names[raw_name] = 1
                    tool_name = raw_name

                operations.append(
                    DiscoveredOperation(
                        tool_name=tool_name,
                        method=method.upper(),
                        path=path,
                        summary=summary,
                        description=description,
                        tag=tag,
                        parameters=parameters,
                        request_body_schema=body_schema,
                        security_schemes=security,
                        is_public=is_public,
                        extension_name=extension,
                    )
                )

        logger.info("Parsed OpenAPI spec", operation_count=len(operations))
        return operations

    # ------------------------------------------------------------------
    # Tool naming
    # ------------------------------------------------------------------

    @staticmethod
    def _build_tool_name(tag: str, method: str, path: str) -> str:
        """Build a readable, unique-ish tool name.

        Format: ``{tag}_{action}_{resource}``
        """
        tag_slug = _slugify(tag)
        action = _METHOD_ACTIONS.get(method, method)

        # Extract resource from the last *meaningful* path segment
        segments = [s for s in path.strip("/").split("/") if not s.startswith("{")]
        resource = segments[-1] if segments else "resource"
        resource_slug = _slugify(resource)

        # For GET list endpoints, prefer "list" over "get"
        if method == "get" and not any(
            s.startswith("{") for s in path.strip("/").split("/")[-1:]
        ):
            # Path does NOT end with a path-param → likely a list endpoint
            if resource_slug not in ("wallet",):
                action = "list"

        return f"{tag_slug}_{action}_{resource_slug}"

    # ------------------------------------------------------------------
    # $ref resolution helpers
    # ------------------------------------------------------------------

    def _resolve_parameters(
        self,
        raw_params: list[dict[str, Any]],
        schemas: dict[str, Any],
    ) -> list[dict[str, Any]]:
        resolved: list[dict[str, Any]] = []
        for p in raw_params:
            p = self._maybe_resolve_ref(p, schemas)
            if "schema" in p:
                p = {**p, "schema": self._resolve_schema(p["schema"], schemas)}
            resolved.append(p)
        return resolved

    def _resolve_request_body(
        self,
        body: dict[str, Any] | None,
        schemas: dict[str, Any],
    ) -> dict[str, Any] | None:
        if body is None:
            return None
        content = body.get("content", {})
        json_content = content.get("application/json", {})
        schema = json_content.get("schema")
        if schema is None:
            return None
        return self._resolve_schema(schema, schemas)

    def _resolve_schema(
        self,
        schema: dict[str, Any],
        schemas: dict[str, Any],
        _depth: int = 0,
    ) -> dict[str, Any]:
        if _depth > 15:
            return schema
        if "$ref" in schema:
            ref_name = schema["$ref"].split("/")[-1]
            resolved = schemas.get(ref_name, {})
            return self._resolve_schema(resolved, schemas, _depth + 1)

        result = dict(schema)
        # Resolve nested properties
        if "properties" in result:
            result["properties"] = {
                k: self._resolve_schema(v, schemas, _depth + 1)
                for k, v in result["properties"].items()
            }
        # Resolve items in arrays
        if "items" in result:
            result["items"] = self._resolve_schema(
                result["items"], schemas, _depth + 1
            )
        # Resolve allOf / anyOf / oneOf
        for combo_key in ("allOf", "anyOf", "oneOf"):
            if combo_key in result:
                result[combo_key] = [
                    self._resolve_schema(s, schemas, _depth + 1)
                    for s in result[combo_key]
                ]
        return result

    def _maybe_resolve_ref(
        self, obj: dict[str, Any], schemas: dict[str, Any]
    ) -> dict[str, Any]:
        if "$ref" in obj:
            ref_name = obj["$ref"].split("/")[-1]
            return schemas.get(ref_name, obj)
        return obj

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_security(security_list: list[dict[str, Any]]) -> list[str]:
        schemes: list[str] = []
        for entry in security_list:
            schemes.extend(entry.keys())
        return schemes

    @staticmethod
    def _detect_extension(path: str) -> str | None:
        """Return the extension name if the path belongs to one, else None."""
        parts = path.strip("/").split("/")
        if len(parts) >= 3 and parts[1] == "api":
            return parts[0]
        return None


def _slugify(text: str) -> str:
    """Convert text to a lowercase snake_case slug."""
    text = text.lower().strip()
    text = re.sub(r"[^a-z0-9]+", "_", text)
    return text.strip("_")
