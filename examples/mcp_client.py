"""Use the real SDK client against the fictional stdio backend only."""
import asyncio
import json
import os
from pathlib import Path
import sys

from mcp import Client
from mcp.client.stdio import StdioServerParameters


async def main():
    source = Path(__file__).resolve().parents[1] / "src"
    # Do not forward live configuration or the caller's PYTHONPATH to the child.
    environment = {key: os.environ[key] for key in ("PATH", "SYSTEMROOT", "WINDIR") if key in os.environ}
    environment.update({"PYTHONPATH": str(source), "PYTHONDONTWRITEBYTECODE": "1"})
    parameters = StdioServerParameters(command=sys.executable,
        args=["-m", "mcp_server", "--backend", "mock"], env=environment, cwd=source)
    async with Client(parameters, read_timeout_seconds=10) as client:
        listing = await client.list_tools()
        result = await client.call_tool("list_guests", {})
        if result.is_error or result.structured_content.get("synthetic") is not True:
            raise RuntimeError("mock demonstration failed")
        print(json.dumps({"transport": "real MCP stdio", "backend": "mock",
                          "tools": [tool.name for tool in listing.tools],
                          "result": result.structured_content}, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
