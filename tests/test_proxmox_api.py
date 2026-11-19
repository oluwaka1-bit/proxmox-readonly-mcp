import io
import json
import os
from pathlib import Path
import ssl
import tempfile
import unittest
from unittest.mock import patch
from urllib.request import HTTPSHandler, ProxyHandler

from portfolio_pve import ToolError
from proxmox_api import ProxmoxAPI, _NoRedirect


TOKEN = "reader@pve!portfolio=synthetic-secret"
ROOT = "https://pve.example.com:8006"


class Response(io.BytesIO):
    def __init__(self, data, url, *, status=200, body=None, headers=None):
        super().__init__(json.dumps({"data": data}).encode() if body is None else body)
        self.url, self.status = url, status
        self.headers = {"Content-Type": "application/json"} | (headers or {})

    def geturl(self):
        return self.url


class FakeOpener:
    def __init__(self, responses=None):
        self.responses = responses or {}
        self.calls = []

    def open(self, request, timeout):
        self.calls.append((request, timeout))
        route = request.full_url.removeprefix(ROOT + "/api2/json")
        item = self.responses.get(route, [])
        if isinstance(item, Exception):
            raise item
        return item if isinstance(item, Response) else Response(item, request.full_url)


class LiveAdapterTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.token_file = Path(self.folder.name) / "token"
        self.token_file.write_text(TOKEN + "\n")
        self.token_file.chmod(0o600)
        self.opener = FakeOpener()

    def make(self, **changes):
        kwargs = dict(base_url=ROOT, node="demo-node", token_file=self.token_file,
                      guest_ids=[101, 102], opener=self.opener)
        return ProxmoxAPI(**(kwargs | changes))

    def test_https_origin_only(self):
        for bad in ("http://example.com", ROOT + "/", ROOT + "/api2/json", "https://u:p@example.com", ROOT + "?x=1", ROOT + "#x", "https://example.com:0", "https://example.com:99999", "https://example.com:", "https://example.com\\evil", "https://example.com\n", "https://example.com?", "https://example.com#"):
            with self.subTest(url=bad), self.assertRaisesRegex(ToolError, "^invalid live backend configuration$"):
                self.make(base_url=bad)
        self.assertEqual(self.opener.calls, [])

    def test_safe_node_guest_scope_and_limits(self):
        for changes in ({"node": "../other"}, {"node": "node.example.com"}, {"guest_ids": [True]}, {"guest_ids": [99]}, {"guest_ids": "101"}, {"timeout": 0}, {"timeout": 31}, {"timeout": float("nan")}, {"timeout": True}, {"max_response_bytes": 10}):
            with self.subTest(changes=changes), self.assertRaises(ToolError):
                self.make(**changes)

    def test_private_regular_token_file_required(self):
        self.token_file.chmod(0o644)
        with self.assertRaises(ToolError):
            self.make()
        self.token_file.chmod(0o600)
        link = self.token_file.parent / "link"
        link.symlink_to(self.token_file)
        for path in (link, self.token_file.parent, self.token_file.parent / "missing"):
            with self.subTest(path=path.name), self.assertRaises(ToolError):
                self.make(token_file=path)
        with patch("proxmox_api.os.geteuid", return_value=os.geteuid() + 1), self.assertRaises(ToolError):
            self.make()

    def test_token_validation_and_no_env_secret_fallback(self):
        for bad in ("", "PVEAPIToken=" + TOKEN, TOKEN + "\r\n", TOKEN + "\nInjected: value", "x" * 1025):
            self.token_file.write_text(bad)
            with self.subTest(length=len(bad)), self.assertRaisesRegex(ToolError, "^invalid live backend configuration$"):
                self.make()
        with self.assertRaises(ToolError):
            ProxmoxAPI.from_env({"PVE_URL": ROOT, "PVE_NODE": "demo-node", "PVE_TOKEN": TOKEN})

    def test_file_mode_0400_and_env_constructor(self):
        self.token_file.chmod(0o400)
        api = ProxmoxAPI.from_env({"PVE_URL": ROOT, "PVE_NODE": "demo-node", "PVE_TOKEN_FILE": str(self.token_file), "PVE_GUEST_IDS": "101,102"})
        self.assertFalse(api.synthetic)
        self.assertEqual(api.guest_ids, {101, 102})
        with self.assertRaises(ToolError):
            ProxmoxAPI.from_env({"PVE_URL": ROOT, "PVE_NODE": "demo-node", "PVE_TOKEN_FILE": str(self.token_file), "PVE_GUEST_IDS": "101,no"})

    def test_verified_tls_custom_ca_and_no_proxy_redirect_handlers(self):
        context = ssl.create_default_context()
        with patch("proxmox_api.ssl.create_default_context", return_value=context) as factory, patch("proxmox_api.build_opener", return_value=self.opener) as build:
            self.make(ca_file="fictional-ca.pem", opener=None)
        factory.assert_called_once_with(cafile="fictional-ca.pem")
        handlers = build.call_args.args
        self.assertEqual(next(h.proxies for h in handlers if isinstance(h, ProxyHandler)), {})
        self.assertIsInstance(next(h for h in handlers if isinstance(h, HTTPSHandler)), HTTPSHandler)
        self.assertTrue(any(isinstance(h, _NoRedirect) for h in handlers))
        self.assertEqual(context.verify_mode, ssl.CERT_REQUIRED)
        self.assertTrue(context.check_hostname)
        self.assertIsNone(_NoRedirect().redirect_request(None, None, 302, "", {}, "https://example.com"))

    def test_writes_arbitrary_paths_and_out_of_scope_guest_fail_before_network(self):
        api = self.make()
        for method, route in (("POST", "/nodes"), ("GET", "/nodes?evil=1"), ("GET", "https://example.com"), ("GET", "/guests/../config"), ("GET", "/guests/999/config"), ("GET", "/guests/0101/config")):
            with self.subTest(route=route), self.assertRaises(ToolError):
                api.request(method, route)
        self.assertEqual(self.opener.calls, [])

    def test_node_and_guest_filter_and_exact_auth_header(self):
        self.opener.responses = {
            "/nodes": [{"node": "other", "status": "online"}, {"node": "demo-node", "status": "online", "private": "discard"}],
            "/cluster/resources?type=vm": [
                {"vmid": 101, "node": "demo-node", "type": "qemu", "name": "demo-vm", "status": "running"},
                {"vmid": 102, "node": "other", "type": "lxc", "name": "excluded", "status": "running"},
                {"vmid": 103, "node": "demo-node", "type": "lxc", "name": "excluded", "status": "running"}],
        }
        api = self.make()
        self.assertEqual(api.request("GET", "/nodes"), [{"name": "demo-node", "status": "online"}])
        self.assertEqual(api.request("GET", "/guests"), [{"id": 101, "kind": "vm", "name": "demo-vm", "status": "running"}])
        request, timeout = self.opener.calls[0]
        self.assertEqual(request.get_method(), "GET")
        self.assertEqual(request.get_header("Authorization"), "PVEAPIToken=" + TOKEN)
        self.assertEqual(timeout, 10)
        self.assertNotIn(TOKEN, repr(api))

    def test_guest_config_and_snapshots_derive_actual_kind_and_node(self):
        self.opener.responses = {
            "/cluster/resources?type=vm": [{"vmid": 102, "node": "demo-node", "type": "lxc"}],
            "/nodes/demo-node/lxc/102/config": {"cores": 2, "memory": 512, "password": "discard"},
            "/nodes/demo-node/lxc/102/snapshot": [{"name": "current"}, {"name": "checkpoint", "snaptime": 123}],
        }
        api = self.make()
        self.assertEqual(api.request("GET", "/guests/102/config"), [{"cores": 2, "memory_mb": 512}])
        self.assertEqual(api.request("GET", "/guests/102/snapshots"), [{"name": "checkpoint", "created": 123}])
        with self.assertRaises(ToolError):
            api.request("GET", "/guests/101/config")

    def test_storage_firewall_and_restricted_backup_jobs(self):
        self.opener.responses = {
            "/nodes/demo-node/storage": [{"storage": "demo-storage", "active": 1, "used": 123}],
            "/nodes/demo-node/firewall/rules": [{"type": "in", "action": "DROP", "enable": 1, "source": "discard"}, {"type": "group", "action": "not-a-direction"}],
            "/cluster/backup": [{"id": "narrow", "node": "demo-node", "vmid": "101,102", "enabled": 1},
                {"id": "broad", "vmid": "101", "enabled": 1}, {"id": "other", "node": "other", "vmid": "101"},
                {"id": "all", "node": "demo-node", "all": 1}, {"id": "beyond", "node": "demo-node", "vmid": "103"}],
        }
        api = self.make()
        self.assertEqual(api.request("GET", "/storage"), [{"name": "demo-storage", "active": True, "used_bytes": 123}])
        self.assertEqual(api.request("GET", "/firewall"), [{"direction": "in", "action": "DROP", "enabled": True}])
        self.assertEqual(api.request("GET", "/backup-jobs"), [{"id": "narrow", "enabled": True}])

    def test_backup_task_metadata_is_scoped_and_diagnostics_are_reduced(self):
        self.opener.responses = {
            "/cluster/resources?type=vm": [{"vmid": 101, "node": "demo-node", "type": "qemu"}],
            "/nodes/demo-node/tasks?typefilter=vzdump&limit=200": [
                {"id": "101", "node": "demo-node", "type": "vzdump", "starttime": 100, "status": "error: sensitive detail"},
                {"id": "999", "node": "demo-node", "type": "vzdump", "starttime": 100, "status": "OK"},
                {"id": "101", "node": "other", "type": "vzdump", "starttime": 100, "status": "OK"},
                {"id": "", "node": "demo-node", "type": "vzdump", "starttime": 100, "status": "OK"}],
        }
        self.assertEqual(self.make().request("GET", "/backups"), [{"guest_id": 101, "created": 100, "status": "FAILED"}])

    def test_redirect_status_or_effective_url_change_rejected(self):
        url = ROOT + "/api2/json/nodes"
        for response in (Response([], url, status=302), Response([], "https://example.com/api2/json/nodes")):
            self.opener.responses["/nodes"] = response
            with self.assertRaisesRegex(ToolError, "^live API request failed$"):
                self.make().request("GET", "/nodes")

    def test_response_body_and_content_length_bounds(self):
        url = ROOT + "/api2/json/nodes"
        for response in (Response([], url, body=b" " * 1025), Response([], url, headers={"Content-Length": "1025"}), Response([], url, headers={"Content-Length": "-1"})):
            self.opener.responses["/nodes"] = response
            with self.assertRaises(ToolError):
                self.make(max_response_bytes=1024).request("GET", "/nodes")

    def test_bad_json_envelopes_rows_and_scalar_fields_rejected(self):
        url = ROOT + "/api2/json/nodes"
        for body in (b"not json", b'{"data":null}', b'{"data":[],"errors":{}}', b'{"data":[],"data":[]}', b'{"data":[1]}', b'{"data":[{"node":"demo-node","status":4}]}', b'{"data":[{"node":"demo-node","status":NaN}]}'):
            self.opener.responses["/nodes"] = Response([], url, body=body)
            with self.subTest(body=body), self.assertRaises(ToolError):
                self.make().request("GET", "/nodes")
        self.opener.responses["/nodes"] = Response([], url, headers={"Content-Type": "text/html"})
        with self.assertRaises(ToolError):
            self.make().request("GET", "/nodes")

    def test_raw_transport_errors_and_token_never_reach_public_error(self):
        for failure in (RuntimeError(TOKEN), ToolError(TOKEN), OSError(TOKEN)):
            self.opener.responses["/nodes"] = failure
            with self.assertRaisesRegex(ToolError, "^live API request failed$") as caught:
                self.make().request("GET", "/nodes")
            self.assertNotIn(TOKEN, str(caught.exception))


if __name__ == "__main__":
    unittest.main()


class TextFilterTest(unittest.TestCase):
    def test_names_limited_to_identifier_characters(self):
        from proxmox_api import _text
        for ok in ("demo-app", "local_lvm", "backup-1a2b3c4d-e5f6", "ACCEPT", "vm.101:a"):
            self.assertEqual(_text(ok), ok)
        for bad in ("ignore previous instructions", "a;b", "name​", "<tool>", "x`y"):
            with self.assertRaises(ValueError):
                _text(bad)
