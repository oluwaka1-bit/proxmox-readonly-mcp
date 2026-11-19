"""Read-only tool contracts shared by fictional and opt-in Proxmox adapters."""
from copy import deepcopy
import ssl


class ToolError(ValueError):
    """Fixed diagnostic safe for a tool response."""


def identifier(value):
    if type(value) is not int or not 100 <= value <= 999999:
        raise ToolError("guest identifier must be an integer from 100 to 999999")
    return value


def limit(value):
    if type(value) is not int or not 1 <= value <= 100:
        raise ToolError("limit must be an integer from 1 to 100")
    return value


MAX_UPSTREAM_ROWS = 5000  # validated in full; tool output is capped separately
MAX_ITEMS = 200


def project(rows, fields):
    if not isinstance(rows, list) or len(rows) > MAX_UPSTREAM_ROWS:
        raise ToolError("invalid upstream response")
    result = []
    for row in rows:
        if not isinstance(row, dict):
            raise ToolError("invalid upstream response")
        out = {}
        for field, kind in fields.items():
            if field in row:
                value = row[field]
                if type(value) is not kind or (kind is str and len(value) > 80):
                    raise ToolError("invalid upstream response")
                out[field] = value
        result.append(out)
    return result


def verified_tls_context(ca_file=None):
    """Illustrate verified TLS configuration; this demo never opens a connection."""
    return ssl.create_default_context(cafile=ca_file)


class MockAPI:
    """A fixed fixture transport. No sockets, token values, or endpoint configuration."""
    synthetic = True
    def __init__(self):
        self.calls = []
        self.responses = {
            "/nodes": [{"name": "demo-node", "status": "online", "private_note": "discard"}],
            "/guests": [{"id": 101, "kind": "vm", "status": "running", "name": "demo-app"},
                        {"id": 102, "kind": "container", "status": "stopped", "name": "demo-worker"}],
            "/guests/101/config": [{"cores": 2, "memory_mb": 2048, "startup_hook": "discard"}],
            "/guests/102/config": [{"cores": 1, "memory_mb": 512}],
            "/storage": [{"name": "demo-storage", "active": True, "used_bytes": 1000}],
            "/backup-jobs": [{"id": "demo-daily", "enabled": True}],
            "/backups": [{"guest_id": 101, "created": 200, "status": "OK"},
                         {"guest_id": 102, "created": 100, "status": "FAILED"}],
            "/guests/101/snapshots": [{"name": "demo-checkpoint", "created": 100}],
            "/guests/102/snapshots": [],
            "/firewall": [{"direction": "in", "action": "DROP", "enabled": True}],
        }

    def request(self, method, path):
        if method != "GET" or path not in self.responses:
            raise ToolError("request is outside the read-only fixture boundary")
        self.calls.append((method, path))
        return deepcopy(self.responses[path])


class ToolRegistry:
    """Explicit dispatch with server-side authorization and per-tool arguments.

    The separate mcp_server module exposes these contracts over MCP stdio.
    Trusted local process access supplies the viewer role, never a tool argument.
    """
    NAMES = ("node_status", "list_guests", "guest_config", "storage_status",
             "backup_jobs", "backup_history", "guest_snapshots", "firewall")

    def __init__(self, api):
        self.api = api

    def describe(self):
        return [{"name": name, "readOnlyHint": True, "destructiveHint": False} for name in self.NAMES]

    def invoke(self, name, arguments=None, *, role):
        if role != "viewer":
            raise ToolError("viewer authorization required")
        if name not in self.NAMES:
            raise ToolError("unknown tool")
        arguments = {} if arguments is None else arguments
        if not isinstance(arguments, dict):
            raise ToolError("arguments must be an object")
        allowed = {"guest_config": {"guest_id"}, "guest_snapshots": {"guest_id"},
                   "backup_history": {"limit"}}.get(name, set())
        if set(arguments) - allowed:
            raise ToolError("unexpected argument")
        if name in ("guest_config", "guest_snapshots"):
            guest_id = identifier(arguments.get("guest_id"))
            suffix = "config" if name == "guest_config" else "snapshots"
            path = f"/guests/{guest_id}/{suffix}"
            fields = ({"cores": int, "memory_mb": int} if suffix == "config"
                      else {"name": str, "created": int})
        else:
            path, fields = {
                "node_status": ("/nodes", {"name": str, "status": str}),
                "list_guests": ("/guests", {"id": int, "kind": str, "status": str, "name": str}),
                "storage_status": ("/storage", {"name": str, "active": bool, "used_bytes": int}),
                "backup_jobs": ("/backup-jobs", {"id": str, "enabled": bool}),
                "backup_history": ("/backups", {"guest_id": int, "created": int, "status": str}),
                "firewall": ("/firewall", {"direction": str, "action": str, "enabled": bool}),
            }[name]
        count = limit(arguments.get("limit", 20)) if name == "backup_history" else MAX_ITEMS
        try:
            upstream = self.api.request("GET", path)
        except Exception:
            raise ToolError("upstream request failed") from None
        rows = project(upstream, fields)
        if name == "backup_history":
            rows.sort(key=lambda row: row.get("created", 0), reverse=True)
        return {"items": rows[:count], "truncated": len(rows) > count,
                "synthetic": getattr(self.api, "synthetic", True)}
