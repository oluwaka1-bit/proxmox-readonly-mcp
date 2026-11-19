# Proxmox Read-only MCP

A Python MCP server for inspecting infrastructure through a small, read-only tool
surface. Start with fictional infrastructure, then explicitly opt into a scoped
HTTPS adapter for your own Proxmox environment.

This reference exposes infrastructure inventory and status without granting
modification privileges or returning every upstream field. It is available under
the [MIT license](LICENSE).

## What works

Eight tools expose node status, guest inventory/configuration, storage, backup jobs,
backup task history, snapshots and firewall rules. The official MCP SDK handles
actual stdio initialization, discovery and execution. Input validation, fixed GET
routes, explicit guest scope and field projection constrain access. Upstream token
privileges independently enforce read-only permissions.

| Backend | Data | Credentials | Evidence |
|---|---|---|---|
| `mock` (default) | Fictional in-memory fixtures | None | Actual local MCP client/server tests |
| `live` (opt-in) | User-configured Proxmox HTTPS API | Private token file | Injected-transport tests, no real-cluster verification |

## Install and try

Requires Python 3.11 or newer; Python 3.13 is the tested SDK environment.
From the repository root:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install --require-hashes -r requirements.lock
.venv/bin/python -m pip install --no-index --no-deps --no-build-isolation -e .
.venv/bin/python examples/mcp_client.py
```

The client launches a stdio server, initializes MCP, lists tools and calls fictional
infrastructure. No Proxmox connection or account is required. A dependency-free
domain example remains available as `python3 examples/demo.py`.

For a host that supports stdio MCP, launch the installed command:

```sh
.venv/bin/proxmox-readonly-mcp --backend mock
```

It waits for MCP messages on stdin, not interactive shell commands. Protocol output
uses stdout. There is no network MCP listener. See [host setup](docs/USAGE.md) and
[generic configuration](examples/mcp-host.json). No host settings are modified.

## Your own Proxmox environment

Live mode requires an explicit backend selection, HTTPS origin, one node, allowed
guest IDs and an owner-only token file. Custom CA bundles are supported with mandatory
verification. Startup settings cannot be changed by tool arguments.

Follow [live setup](docs/USAGE.md#live-backend) for token format, permissions and
limitations. `.env.example` documents settings; it is not loaded automatically.
No real endpoint or credential is supplied. Do not commit live settings or output.

## Architecture and security decisions

[The diagram](docs/architecture.md) shows the local host, MCP server, validated
registry and separate mock/HTTPS adapters.

- Stdio process access is the trust boundary; no remote user authentication is claimed.
- Tools cannot choose a URL, node, role, HTTP method or arbitrary path.
- The live adapter rejects redirects, ignores proxy environment settings, verifies
  TLS and bounds response size and body-read time. Upstream ACLs remain necessary.
- Inventory lists return at most 200 items. The `truncated` field indicates when
  the server omitted available rows to honor a result limit.
- The live adapter rejects responses with invalid identifier text in projected
  fields such as guest, storage and snapshot names.
- Field filtering is not privacy redaction: real strings can still disclose details.
- Backup jobs and task metadata do not prove that a backup can restore.

## Tests, limits and evidence

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -v
```

Tests exercise domain restrictions, fake HTTPS responses and real local MCP stdio
sessions. No test contacts a live cluster. See [claims](docs/CLAIMS.md),
[readiness](reports/READINESS.md) and [security review](reports/SECURITY_REVIEW.md)
for results and gaps.

Live API schemas, token ACLs and certificate deployment require testing in the
target environment.
Response limits intentionally reject oversized payloads. No complete cluster
inventory, rate limiting, modifications, remediation or restore operation is provided.

Planned improvements include versioned compatibility fixtures, stricter semantic
response schemas and disposable-cluster integration tests. Read [SECURITY.md](SECURITY.md)
and [dependency notices](NOTICE.md).
