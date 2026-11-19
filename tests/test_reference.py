import ssl
import unittest
from portfolio_pve import MockAPI, ToolError, ToolRegistry, verified_tls_context


class ReferenceTests(unittest.TestCase):
    def setUp(self):
        self.api = MockAPI()
        self.tools = ToolRegistry(self.api)

    def call(self, name, args=None):
        return self.tools.invoke(name, args, role="viewer")

    def test_all_eight_tools_execute_get_only(self):
        for name in self.tools.NAMES:
            args = {"guest_id": 101} if name in ("guest_config", "guest_snapshots") else {}
            self.assertTrue(self.call(name, args)["synthetic"])
        self.assertEqual(len(self.api.calls), 8)
        self.assertTrue(all(method == "GET" for method, _ in self.api.calls))

    def test_allowlist_excludes_unreviewed_fields(self):
        self.assertEqual(self.call("guest_config", {"guest_id": 101})["items"],
                         [{"cores": 2, "memory_mb": 2048}])
        self.assertNotIn("private_note", self.call("node_status")["items"][0])

    def test_authorization_precedes_transport(self):
        with self.assertRaises(ToolError):
            self.tools.invoke("list_guests", role="admin")
        self.assertFalse(self.api.calls)

    def test_bool_and_path_injection_guest_ids_rejected(self):
        for bad in (True, "../nodes", 99, 1000000, None):
            with self.subTest(bad=bad), self.assertRaises(ToolError):
                self.call("guest_config", {"guest_id": bad})
        self.assertFalse(self.api.calls)

    def test_unknown_tool_and_extra_arguments_rejected(self):
        for name, args in (("delete_guest", {}), ("list_guests", {"path": "/secrets"})):
            with self.assertRaises(ToolError):
                self.call(name, args)
        self.assertFalse(self.api.calls)

    def test_backup_limit_and_order(self):
        self.assertEqual(self.call("backup_history", {"limit": 1})["items"][0]["created"], 200)
        for bad in (True, 0, 101, "2"):
            with self.assertRaises(ToolError):
                self.call("backup_history", {"limit": bad})

    def test_transport_refuses_writes(self):
        with self.assertRaises(ToolError):
            self.api.request("POST", "/nodes")

    def test_bad_upstream_shapes_rejected(self):
        for payload in ({"items": []}, ["bad"], [{"status": 1}], [{}] * 5001):
            self.api.responses["/nodes"] = payload
            with self.assertRaises(ToolError):
                self.call("node_status")

    def test_long_lists_are_capped_and_flagged(self):
        self.api.responses["/storage"] = [{"name": f"s{i}", "active": True, "used_bytes": i} for i in range(250)]
        result = self.call("storage_status")
        self.assertEqual(len(result["items"]), 200)
        self.assertTrue(result["truncated"])
        self.assertFalse(self.call("node_status")["truncated"])

    def test_transport_failure_is_sanitized(self):
        class Broken:
            def request(self, *_):
                raise RuntimeError("unreviewed upstream detail")
        with self.assertRaisesRegex(ToolError, "^upstream request failed$"):
            ToolRegistry(Broken()).invoke("node_status", role="viewer")

    def test_transport_tool_error_is_sanitized(self):
        class Broken:
            def request(self, *_):
                raise ToolError("sensitive upstream body")
        with self.assertRaisesRegex(ToolError, "^upstream request failed$") as caught:
            ToolRegistry(Broken()).invoke("node_status", role="viewer")
        self.assertNotIn("sensitive upstream body", str(caught.exception))

    def test_tls_requires_chain_and_hostname_verification(self):
        context = verified_tls_context()
        self.assertEqual(context.verify_mode, ssl.CERT_REQUIRED)
        self.assertTrue(context.check_hostname)


if __name__ == "__main__":
    unittest.main()
