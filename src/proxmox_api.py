"""Opt-in, verified HTTPS adapter. No networking occurs during construction.

Token-file format: user@realm!token-id=secret (one ASCII line, mode 0400/0600).
Only the fixed virtual routes used by ToolRegistry are supported. Backup jobs
must name this node and an explicit subset of permitted guests; broad jobs are
omitted. Backup history is at most 200 finished vzdump task records, not backup
archive inventory or restore evidence. No task text, users, or UPIDs are returned.
"""
import ipaddress
import json
import math
import os
import re
import ssl
import stat
import time
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, HTTPSHandler, ProxyHandler, Request, build_opener

from portfolio_pve import ToolError, identifier


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _text(value, maximum=80):
    if type(value) is not str or not 1 <= len(value) <= maximum or any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise ValueError("invalid scalar")
    # Names come from whoever can edit the cluster and are shown to the model, so they
    # are a prompt-injection surface. Restrict them to a conservative character set.
    # No spaces: Proxmox identifiers never need them, and without them a name cannot
    # carry a sentence-like instruction.
    if not re.fullmatch(r"[A-Za-z0-9._:-]+", value):
        raise ValueError("invalid scalar")
    return value


def _integer(value, minimum=0):
    if type(value) is not int or value < minimum:
        raise ValueError("invalid scalar")
    return value


def _boolean(value):
    if type(value) is bool:
        return value
    if type(value) is int and value in (0, 1):
        return bool(value)
    raise ValueError("invalid scalar")


def _base_url(value):
    if type(value) is not str or not value or any(ord(c) < 33 or ord(c) > 126 for c in value):
        raise ValueError("invalid URL")
    parsed = urlsplit(value)
    if parsed.scheme != "https" or not parsed.netloc or parsed.path or parsed.query or parsed.fragment or parsed.username is not None or parsed.password is not None:
        raise ValueError("invalid URL")
    if any(c in value for c in ("\\", "%", "?", "#")):
        raise ValueError("invalid URL")
    host = parsed.hostname
    if not host or parsed.port is not None and not 1 <= parsed.port <= 65535:
        raise ValueError("invalid URL")
    try:
        ipaddress.ip_address(host)
    except ValueError:
        if len(host) > 253 or any(not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?", label) for label in host.split(".")):
            raise ValueError("invalid URL") from None
    # An empty explicit port is ambiguous and is not accepted.
    if parsed.netloc.endswith(":"):
        raise ValueError("invalid URL")
    return value


def _token_from_file(path):
    fd = None
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode & 0o077 or not info.st_mode & stat.S_IRUSR or not 1 <= info.st_size <= 1024:
            raise ValueError("invalid credential file")
        raw = os.read(fd, 1025)
        if len(raw) > 1024:
            raise ValueError("invalid credential file")
        value = raw.decode("ascii")
        if value.endswith("\n"):
            value = value[:-1]
        if re.fullmatch(r"[A-Za-z0-9_.-]+@[A-Za-z0-9_.-]+![A-Za-z0-9_.-]+=[A-Za-z0-9_-]{8,256}", value) is None:
            raise ValueError("invalid credential file")
        return value
    finally:
        if fd is not None:
            os.close(fd)


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


class ProxmoxAPI:
    synthetic = False

    def __init__(self, base_url, node, token_file, guest_ids=(), *, ca_file=None,
                 timeout=10, max_response_bytes=1048576, opener=None):
        try:
            self.base_url = _base_url(base_url)
            if type(node) is not str or not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?", node):
                raise ValueError("invalid node")
            self.node = node
            if isinstance(guest_ids, (str, bytes, dict)):
                raise ValueError("invalid guest scope")
            permitted = tuple(guest_ids)
            if len(permitted) > 200:
                raise ValueError("invalid guest scope")
            self.guest_ids = frozenset(identifier(item) for item in permitted)
            if type(timeout) not in (int, float) or not math.isfinite(timeout) or not 1 <= timeout <= 30:
                raise ValueError("invalid timeout")
            if type(max_response_bytes) is not int or not 1024 <= max_response_bytes <= 4194304:
                raise ValueError("invalid response limit")
            self.timeout, self.max_response_bytes = timeout, max_response_bytes
            self.tls_context = ssl.create_default_context(cafile=ca_file)
            if self.tls_context.verify_mode != ssl.CERT_REQUIRED or not self.tls_context.check_hostname:
                raise ValueError("unverified TLS context")
            self.__token = _token_from_file(token_file)
            self._opener = opener if opener is not None else build_opener(
                ProxyHandler({}), HTTPSHandler(context=self.tls_context), _NoRedirect())
        except Exception:
            raise ToolError("invalid live backend configuration") from None

    @classmethod
    def from_env(cls, env=None):
        """Read configuration paths and scope only, never a token value from env."""
        try:
            env = os.environ if env is None else env
            scope = env.get("PVE_GUEST_IDS", "")
            ids = [] if scope == "" else [int(part) for part in scope.split(",") if re.fullmatch(r"[0-9]{3,6}", part)]
            if scope and len(ids) != len(scope.split(",")):
                raise ValueError("invalid guest scope")
            return cls(env["PVE_URL"], env["PVE_NODE"], env["PVE_TOKEN_FILE"], ids,
                       ca_file=env.get("PVE_CA_FILE") or None,
                       timeout=float(env.get("PVE_TIMEOUT", "10")))
        except Exception:
            raise ToolError("invalid live backend configuration") from None

    def _fetch(self, route):
        url = self.base_url + "/api2/json" + route
        request = Request(url, method="GET", headers={
            "Authorization": "PVEAPIToken=" + self.__token,
            "Accept": "application/json", "Accept-Encoding": "identity",
        })
        deadline = time.monotonic() + self.timeout
        try:
            with self._opener.open(request, timeout=self.timeout) as response:
                if response.status != 200 or response.geturl() != url:
                    raise ValueError("unexpected HTTP response")
                if response.headers.get("Content-Type", "").split(";", 1)[0].strip().lower() != "application/json":
                    raise ValueError("unexpected content type")
                length = response.headers.get("Content-Length")
                if length is not None and (not re.fullmatch(r"[0-9]+", length) or int(length) > self.max_response_bytes):
                    raise ValueError("invalid content length")
                # The socket timeout bounds each read; this deadline bounds the whole body,
                # so a server that drips bytes cannot hold a call open indefinitely.
                chunks, size = [], 0
                while True:
                    if time.monotonic() > deadline:
                        raise ValueError("response deadline exceeded")
                    chunk = response.read(min(65536, self.max_response_bytes + 1 - size))
                    if type(chunk) is not bytes:
                        raise ValueError("invalid response body")
                    if not chunk:
                        break
                    chunks.append(chunk)
                    size += len(chunk)
                    if size > self.max_response_bytes:
                        raise ValueError("response too large")
                content = b"".join(chunks)
            payload = json.loads(content.decode("utf-8"), object_pairs_hook=_unique_object,
                                 parse_constant=lambda _: (_ for _ in ()).throw(ValueError("invalid JSON constant")))
            if type(payload) is not dict or "data" not in payload or "errors" in payload or not isinstance(payload["data"], (dict, list)):
                raise ValueError("invalid response envelope")
            return payload["data"]
        except Exception:
            raise ToolError("live API request failed") from None

    def _rows(self, data):
        if type(data) is not list or len(data) > 5000 or any(type(row) is not dict for row in data):
            raise ValueError("invalid response rows")
        return data

    def _guests(self):
        rows = self._rows(self._fetch("/cluster/resources?type=vm"))
        result = {}
        for row in rows:
            if row.get("node") != self.node or row.get("vmid") not in self.guest_ids:
                continue
            guest_id = identifier(row["vmid"])
            if row.get("type") not in ("qemu", "lxc") or guest_id in result:
                raise ValueError("invalid guest response")
            result[guest_id] = row
        return result

    def request(self, method, path):
        """Map virtual registry paths to fixed GETs; no arbitrary upstream URLs."""
        if method != "GET" or type(path) is not str:
            raise ToolError("request outside read-only live boundary")
        fixed = {"/nodes", "/guests", "/storage", "/backup-jobs", "/backups", "/firewall"}
        match = re.fullmatch(r"/guests/([0-9]{3,6})/(config|snapshots)", path)
        if path not in fixed and match is None:
            raise ToolError("request outside read-only live boundary")
        try:
            if match:
                guest_id = identifier(int(match[1]))
                if match[1] != str(guest_id) or guest_id not in self.guest_ids:
                    raise ValueError("guest outside scope")
                guest = self._guests().get(guest_id)
                if guest is None:
                    raise ValueError("guest unavailable in scope")
                suffix = "config" if match[2] == "config" else "snapshot"
                data = self._fetch(f"/nodes/{self.node}/{guest['type']}/{guest_id}/{suffix}")
                if suffix == "config":
                    if type(data) is not dict:
                        raise ValueError("invalid config")
                    return [{target: _integer(data[source], 1) for source, target in (("cores", "cores"), ("memory", "memory_mb")) if source in data}]
                return [{"name": _text(row["name"]), "created": _integer(row["snaptime"])}
                        for row in self._rows(data) if row.get("name") != "current"]
            if path == "/nodes":
                return [{"name": self.node, "status": _text(row["status"])}
                        for row in self._rows(self._fetch("/nodes")) if row.get("node") == self.node]
            if path == "/guests":
                return [{"id": guest_id, "kind": "vm" if row["type"] == "qemu" else "container",
                         "status": _text(row["status"]), "name": _text(row["name"])}
                        for guest_id, row in self._guests().items()]
            if path == "/storage":
                return [{"name": _text(row["storage"]), "active": _boolean(row["active"]), "used_bytes": _integer(row["used"])}
                        for row in self._rows(self._fetch(f"/nodes/{self.node}/storage"))]
            if path == "/backup-jobs":
                result = []
                for row in self._rows(self._fetch("/cluster/backup")):
                    if row.get("node") != self.node or row.get("all") or row.get("pool") or row.get("exclude"):
                        continue
                    selected = row.get("vmid")
                    if type(selected) is not str or not re.fullmatch(r"[0-9]{3,6}(?:[ ,;][0-9]{3,6})*", selected):
                        continue
                    ids = {identifier(int(part)) for part in re.split(r"[ ,;]", selected)}
                    if ids and ids <= self.guest_ids:
                        result.append({"id": _text(row["id"]), "enabled": _boolean(row.get("enabled", 1))})
                return result
            if path == "/backups":
                result = []
                guests = self._guests()
                for row in self._rows(self._fetch(f"/nodes/{self.node}/tasks?typefilter=vzdump&limit=200")):
                    task_id = row.get("id")
                    if row.get("node") != self.node or row.get("type") != "vzdump" or type(task_id) is not str or not re.fullmatch(r"[0-9]{3,6}", task_id):
                        continue
                    guest_id = identifier(int(task_id))
                    if guest_id in guests:
                        status = row.get("status")
                        result.append({"guest_id": guest_id, "created": _integer(row["starttime"]),
                                       "status": "UNKNOWN" if status is None else "OK" if status == "OK" else "FAILED"})
                return result
            return [{"direction": _text(row["type"]), "action": _text(row["action"]), "enabled": _boolean(row.get("enable", 0))}
                    for row in self._rows(self._fetch(f"/nodes/{self.node}/firewall/rules")) if row.get("type") in ("in", "out")]
        except Exception:
            raise ToolError("live API request failed") from None
