"""LNbits MCP Server — dynamic tool discovery from OpenAPI spec."""

import asyncio
import sys
from typing import Any, Dict, Optional

import structlog
from mcp import types
from mcp.server import Server
from mcp.server.models import InitializationOptions
from mcp.server.stdio import stdio_server
from mcp.types import Tool

from .client import LNbitsConfig, LNbitsError
from .discovery.dispatcher import Dispatcher
from .discovery.meta_tools import META_TOOL_NAMES, MetaTools
from .discovery.openapi_parser import OpenAPIParser
from .discovery.tool_registry import ToolRegistry
from .utils.runtime_config import RuntimeConfigManager

logger = structlog.get_logger(__name__)


class LNbitsMCPServer:
    """LNbits MCP Server with dynamic OpenAPI-based tool discovery."""

    def __init__(self, config: Optional[LNbitsConfig] = None):
        self.config = config or LNbitsConfig()
        self.server = Server("lnbits-mcp-server")

        # Runtime configuration manager
        self.config_manager = RuntimeConfigManager(self.config)

        # Discovery components
        self.registry = ToolRegistry()
        self.dispatcher = Dispatcher()
        self.meta_tools = MetaTools(self.config_manager)
        self.meta_tools.set_callbacks(
            refresh_fn=self._discover_tools,
            get_extensions_fn=self.registry.get_extensions,
        )

        # Wire config change callback
        self.config_manager.on_config_changed = self._on_config_changed

        self._discovery_done = False

        # Register MCP handlers
        self._register_handlers()

    # ------------------------------------------------------------------
    # Discovery
    # ------------------------------------------------------------------

    async def _discover_tools(self) -> int:
        """Fetch OpenAPI spec and populate the tool registry. Returns tool count."""
        url = str(self.config_manager.config.lnbits_url).rstrip("/")
        parser = OpenAPIParser(url)
        try:
            operations = await parser.fetch_and_parse()
            count = self.registry.load(operations)
            self._discovery_done = True
            logger.info("Tool discovery complete", tool_count=count)

            # Notify MCP clients that the tool list changed
            try:
                await self.server.request_context.session.send_tool_list_changed()
            except Exception:
                pass  # No active session yet during initial discovery

            return count
        except Exception as e:
            logger.warning("Tool discovery failed — serving meta tools only", error=str(e))
            return 0

    async def _on_config_changed(self) -> None:
        """Called when the user reconfigures the LNbits URL."""
        await self._discover_tools()

    # ------------------------------------------------------------------
    # MCP handlers
    # ------------------------------------------------------------------

    def _register_handlers(self) -> None:
        @self.server.list_tools()
        async def list_tools() -> list[Tool]:
            # Lazy discovery on first call
            if not self._discovery_done:
                await self._discover_tools()

            tools = self.meta_tools.get_tools() + self.registry.get_mcp_tools()
            logger.info("list_tools", count=len(tools))
            return tools

        @self.server.call_tool()
        async def call_tool(name: str, arguments: Dict[str, Any]) -> list[types.TextContent]:
            try:
                logger.info("call_tool", tool=name)

                # Meta tools
                if name in META_TOOL_NAMES:
                    text = await self.meta_tools.call_tool(name, arguments)
                    return [types.TextContent(type="text", text=text)]

                # Discovered tools
                op = self.registry.get(name)
                if op is None:
                    return [types.TextContent(
                        type="text",
                        text=f"Unknown tool: {name}",
                    )]

                client = await self.config_manager.get_client()
                text = await self.dispatcher.dispatch(client, op, arguments)
                return [types.TextContent(type="text", text=text)]

            except LNbitsError as e:
                logger.error("LNbits API error", error=str(e), tool=name)
                return [types.TextContent(
                    type="text",
                    text=f"LNbits API error: {e}",
                )]
            except Exception as e:
                logger.error("Unexpected error", error=str(e), tool=name, exc_info=True)
                return [types.TextContent(
                    type="text",
                    text=f"Error: {e}",
                )]

    # ------------------------------------------------------------------
    # Run
    # ------------------------------------------------------------------

    async def run(self) -> None:
        logger.info("Starting LNbits MCP server")
        try:
            async with stdio_server() as (read_stream, write_stream):
                await self.server.run(
                    read_stream,
                    write_stream,
                    InitializationOptions(
                        server_name="lnbits-mcp-server",
                        server_version="0.2.0",
                        capabilities=types.ServerCapabilities(
                            tools=types.ToolsCapability(listChanged=True),
                        ),
                    ),
                )
        finally:
            await self.config_manager.close()


# ------------------------------------------------------------------
# Entry points
# ------------------------------------------------------------------


async def async_main() -> None:
    structlog.configure(
        processors=[
            structlog.stdlib.filter_by_level,
            structlog.stdlib.add_logger_name,
            structlog.stdlib.add_log_level,
            structlog.stdlib.PositionalArgumentsFormatter(),
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.UnicodeDecoder(),
            structlog.processors.JSONRenderer(),
        ],
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    try:
        server = LNbitsMCPServer()
        await server.run()
    except KeyboardInterrupt:
        logger.info("Server shutdown requested")
    except Exception as e:
        logger.error("Server error", error=str(e), exc_info=True)
        sys.exit(1)


def main() -> None:
    """Synchronous entry point for console script."""
    asyncio.run(async_main())


if __name__ == "__main__":
    main()
