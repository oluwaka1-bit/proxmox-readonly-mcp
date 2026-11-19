"""Real stdio subprocess MCP checks. All servers explicitly select mock data."""
from functools import wraps
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch


SDK_AVAILABLE = importlib.util.find_spec("mcp") is not None
if SDK_AVAILABLE:
    from mcp import Client
    from mcp.client.stdio import StdioServerParameters
    from mcp_server import build_registry, build_server
    from portfolio_pve import ToolRegistry

SOURCE = Path(__file__).resolve().parents[1] / "src"
NAMES = {"node_status", "list_guests", "guest_config", "storage_status",
         "backup_jobs", "backup_history", "guest_snapshots", "firewall"}


def child_environment():
    environment = {key: os.environ[key] for key in ("PATH", "SYSTEMROOT", "WINDIR") if key in os.environ}
    environment.update({"PYTHONPATH": str(SOURCE), "PYTHONDONTWRITEBYTECODE": "1"})
    return environment


def with_stdio_client(method):
    @wraps(method)
    async def run(self):
        parameters = StdioServerParameters(command=sys.executable,
            args=["-m", "mcp_server", "--backend", "mock"], env=child_environment(), cwd=SOURCE)
        # AnyIO enter/exit must stay in the same task. unittest asyncSetUp and
        # addAsyncCleanup use separate tasks, so scope the client in each test.
        async with Client(parameters, read_timeout_seconds=10) as client:
            self.client = client
            await method(self)
    return run


@unittest.skipUnless(SDK_AVAILABLE, "install the pinned MCP SDK to run protocol integration tests")
class StdioTests(unittest.IsolatedAsyncioTestCase):
    async def test_live_annotations_declare_external_world_without_network(self):
        class NeverCalledLiveAPI:
            synthetic = False
            def request(self, *_):
                raise AssertionError("annotation inspection must not make requests")
        server = build_server(ToolRegistry(NeverCalledLiveAPI()))
        async with Client(server, read_timeout_seconds=10) as client:
            listing = await client.list_tools()
        self.assertEqual({tool.name for tool in listing.tools}, NAMES)
        for tool in listing.tools:
            self.assertTrue(tool.annotations.open_world_hint)
            self.assertTrue(tool.annotations.read_only_hint)
            self.assertFalse(tool.annotations.destructive_hint)

    @with_stdio_client
    async def test_real_handshake_lists_eight_read_only_tools_and_strict_schemas(self):
        listing = await self.client.list_tools()
        self.assertEqual({tool.name for tool in listing.tools}, NAMES)
        for tool in listing.tools:
            self.assertTrue(tool.annotations.read_only_hint)
            self.assertFalse(tool.annotations.destructive_hint)
            self.assertTrue(tool.annotations.idempotent_hint)
            self.assertFalse(tool.input_schema["additionalProperties"])
            self.assertNotIn("role", tool.input_schema["properties"])
            if tool.name in ("guest_config", "guest_snapshots"):
                self.assertEqual(tool.input_schema["required"], ["guest_id"])

    @with_stdio_client
    async def test_all_eight_tools_round_trip_over_stdio(self):
        for name in sorted(NAMES):
            args = {"guest_id": 101} if name in ("guest_config", "guest_snapshots") else {}
            result = await self.client.call_tool(name, args)
            with self.subTest(name=name):
                self.assertFalse(result.is_error)
                self.assertTrue(result.structured_content["synthetic"])
                self.assertIsInstance(result.structured_content["items"], list)
                self.assertEqual(json.loads(result.content[0].text), result.structured_content)

    @with_stdio_client
    async def test_sdk_does_not_coerce_bool_or_string_ids(self):
        for bad in (True, "101", 101.0, "../nodes", 99):
            with self.subTest(bad=bad):
                result = await self.client.call_tool("guest_config", {"guest_id": bad})
                self.assertTrue(result.is_error)
                self.assertEqual(result.content[0].text,
                                 "guest identifier must be an integer from 100 to 999999")

    @with_stdio_client
    async def test_unknown_tool_has_fixed_error_and_session_survives(self):
        result = await self.client.call_tool("not-a-tool-sensitive-text", {})
        self.assertTrue(result.is_error)
        self.assertEqual(result.content[0].text, "unknown tool")
        self.assertFalse((await self.client.call_tool("node_status", {})).is_error)

    @with_stdio_client
    async def test_missing_extra_and_credential_arguments_rejected(self):
        for name, arguments in (("guest_config", {}), ("list_guests", {"token": "untrusted-text"}),
                                ("list_guests", {"role": "admin"}), ("backup_history", {"limit": "1"}),
                                ("backup_history", {"limit": True}), ("backup_history", {"limit": 0})):
            with self.subTest(name=name, arguments=arguments):
                result = await self.client.call_tool(name, arguments)
                self.assertTrue(result.is_error)
                self.assertNotIn("untrusted-text", result.content[0].text)


@unittest.skipUnless(SDK_AVAILABLE, "install the pinned MCP SDK to run protocol integration tests")
class StartupTests(unittest.TestCase):
    def test_mock_construction_never_imports_live_adapter_or_reads_config(self):
        class ForbiddenEnvironment:
            def __getitem__(self, key):
                raise AssertionError("live environment read in mock mode")
            def get(self, *args):
                raise AssertionError("live environment read in mock mode")
        with patch.dict(sys.modules, {"proxmox_api": None}):
            registry = build_registry("mock", environ=ForbiddenEnvironment())
        self.assertTrue(registry.invoke("node_status", role="viewer")["synthetic"])

    def test_explicit_live_with_missing_config_fails_before_protocol_start(self):
        result = subprocess.run([sys.executable, "-m", "mcp_server", "--backend", "live"],
                                cwd=SOURCE, env=child_environment(), capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, "")
        self.assertEqual(result.stderr.strip(), "MCP startup configuration rejected")

    def test_default_backend_ignores_bad_live_configuration_and_stdout_is_protocol_only(self):
        environment = child_environment()
        environment.update({"PVE_URL": "invalid-sensitive-config", "PVE_NODE": "invalid-sensitive-config",
                            "PVE_TOKEN_FILE": "unavailable-token-file", "PVE_CA_FILE": "unavailable-ca-file"})
        request = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
            "protocolVersion": "2025-11-25", "capabilities": {},
            "clientInfo": {"name": "offline-fixture", "version": "1"}}}
        completed = subprocess.run([sys.executable, "-m", "mcp_server"], cwd=SOURCE,
            env=environment, input=json.dumps(request) + "\n", capture_output=True, text=True, timeout=10)
        self.assertEqual(completed.returncode, 0)
        messages = [json.loads(line) for line in completed.stdout.splitlines()]
        self.assertTrue(messages, "server must emit a protocol response")
        self.assertTrue(all(message.get("jsonrpc") == "2.0" for message in messages))
        self.assertTrue(any(message.get("id") == 1 and "result" in message for message in messages))
        self.assertNotIn("invalid-sensitive-config", completed.stdout + completed.stderr)


if __name__ == "__main__":
    unittest.main()
