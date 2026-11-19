"""Real MCP stdio server with strict registry dispatch and explicit backend choice.

The SDK owns negotiation and framing. Explicit protocol schemas advertise the
contract; the registry validates raw arguments without SDK integer coercion.
No HTTP listener, credential-valued tool parameter, or host-side write exists.
"""
from __future__ import annotations

import argparse
import asyncio
from copy import deepcopy
import json
import logging
import sys

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import CallToolResult, ListToolsResult, TextContent, Tool, ToolAnnotations

from portfolio_pve import MockAPI, ToolError, ToolRegistry


DESCRIPTIONS = {
    "node_status": "Read status of the configured node; no infrastructure modifications.",
    "list_guests": "List configured-scope virtual machines and containers.",
    "guest_config": "Read selected resource configuration of one scoped guest.",
    "storage_status": "Read selected storage availability and usage fields.",
    "backup_jobs": "Read selected backup scheduling metadata.",
    "backup_history": "Read recent backup task metadata; this does not verify restore success.",
    "guest_snapshots": "Read snapshot metadata for one scoped guest.",
    "firewall": "Inspect selected firewall rules; no rule changes are available.",
}


def tool_definitions(*, synthetic=True):
    definitions = []
    for name in ToolRegistry.NAMES:
        schema = {"type": "object", "properties": {}, "additionalProperties": False}
        if name in ("guest_config", "guest_snapshots"):
            schema["properties"]["guest_id"] = {
                "type": "integer", "minimum": 100, "maximum": 999999,
                "description": "A guest identifier permitted by startup configuration.",
            }
            schema["required"] = ["guest_id"]
        elif name == "backup_history":
            schema["properties"]["limit"] = {
                "type": "integer", "minimum": 1, "maximum": 100, "default": 20,
            }
        definitions.append(Tool(
            name=name, description=DESCRIPTIONS[name], input_schema=schema,
            annotations=ToolAnnotations(read_only_hint=True, destructive_hint=False,
                                        idempotent_hint=True, open_world_hint=not synthetic),
        ))
    return definitions


def build_registry(backend="mock", *, environ=None):
    """Load secrets/configuration only after an explicit live startup choice."""
    if backend == "mock":
        return ToolRegistry(MockAPI())
    if backend == "live":
        # Importing the adapter and reading live configuration are opt-in.
        from proxmox_api import ProxmoxAPI
        return ToolRegistry(ProxmoxAPI.from_env(environ))
    raise ToolError("unknown backend")


def build_server(registry):
    definitions = tool_definitions(synthetic=getattr(registry.api, "synthetic", True))

    async def list_tools(context, params):
        return ListToolsResult(tools=deepcopy(definitions))

    async def call_tool(context, params):
        try:
            result = registry.invoke(params.name, params.arguments, role="viewer")
        except ToolError as error:
            # Registry validation messages are fixed; transport errors are
            # replaced with a fixed message inside the registry first.
            return CallToolResult(content=[TextContent(type="text", text=str(error))], is_error=True)
        except Exception:
            return CallToolResult(content=[TextContent(type="text", text="tool execution failed")], is_error=True)
        return CallToolResult(content=[TextContent(type="text", text=json.dumps(result, sort_keys=True))],
                              structured_content=result)

    return Server(
        "read-only-proxmox-reference", version="0.2.0",
        instructions=("Read-only inventory tools. The default backend is fictional. "
                      "Live scope and credentials are selected only by the host at startup. "
                      "Backup metadata is not proof of a successful restore."),
        on_list_tools=list_tools, on_call_tool=call_tool,
    )


async def serve(registry):
    server = build_server(registry)
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


def main(argv=None):
    parser = argparse.ArgumentParser(description="Read-only Proxmox MCP server over local stdio")
    parser.add_argument("--backend", choices=("mock", "live"), default="mock",
                        help="mock is offline; live requires explicit host environment configuration")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.WARNING, stream=sys.stderr)
    try:
        registry = build_registry(args.backend)
    except Exception:
        # Never echo a token, path, URL, or raw parser/transport exception.
        print("MCP startup configuration rejected", file=sys.stderr)
        return 2
    try:
        asyncio.run(serve(registry))
    except KeyboardInterrupt:
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
