# Setup and integration

## MCP host

Install using the README. Configure a host with local stdio MCP support to launch
the absolute path to `.venv/bin/proxmox-readonly-mcp` with `--backend mock`.
`examples/mcp-host.json` illustrates a common JSON layout; host formats differ.
Replace placeholder paths and follow your host's documentation. No configuration
filename is universal, and nothing is installed into host settings automatically.

The default mock backend ignores live credential settings. The included
`examples/mcp_client.py` uses the actual SDK without depending on a specific chat
application. A successful handshake verifies protocol behavior, not a real deployment.

## Live backend

Only use this with your own approved environment. Live-cluster compatibility
remains unverified. Keep stdio process access restricted.

1. Create a dedicated Proxmox API token with privilege separation. Give the user
   and token only the required read permissions. Effective access depends on both
   identities and their ACLs. Start with applicable audit permissions, narrow paths
   to your intended node/guests, and inspect effective permissions in the official
   API viewer. Do not grant administration rights to bypass a failing tool.
2. Create an owner-only regular token file with a trusted local editor. Use mode
   `0600`. Its single-line value is `user@realm!token-id=token-secret`, without the
   `PVEAPIToken=` prefix. Never put a secret in a shell command, tool argument or
   committed host configuration. The process owner can access this file.
3. Set startup environment values through the trusted host. These are fictional:

```sh
export PVE_URL=https://proxmox.example.com:8006
export PVE_NODE=example-node
export PVE_GUEST_IDS=101,102
export PVE_TOKEN_FILE=/absolute/path/to/private/proxmox.token
# Optional private CA bundle. Omit when the system trust store validates the server.
export PVE_CA_FILE=/absolute/path/to/private/cluster-ca.pem
export PVE_TIMEOUT=10
```

The URL must be an HTTPS origin with no credentials, API path, query or fragment.
The adapter adds `/api2/json` and fixed paths. There is no insecure TLS option.
`.env.example` is documentation, not a dotenv loader. An omitted or empty guest scope denies all guest reads. Guest IDs restrict this
application in addition to token ACLs. Keep token files outside the repository or
inside an ignored private directory; ignore rules do not replace secret scanning.

4. Launch `.venv/bin/proxmox-readonly-mcp --backend live` through the host. Only this
   explicit selection enables HTTPS. Begin with one read call in an approved
   environment and inspect returned fields locally.

## Tool scope

| Tool | Arguments | Scope |
|---|---|---|
| `node_status` | none | Configured node |
| `list_guests` | none | Configured node and allowed guests |
| `guest_config` | integer `guest_id` | Allowed VM/LXC |
| `storage_status` | none | Configured node |
| `backup_jobs` | none | Jobs explicitly assigned to the node |
| `backup_history` | bounded integer `limit` | Node backup-task metadata |
| `guest_snapshots` | integer `guest_id` | Allowed VM/LXC |
| `firewall` | none | Node firewall rules |

Jobs without an explicit node can be omitted deliberately. Task history does not
enumerate archive contents or prove restore success. Check documented adapter
filtering before assuming completeness. Particular tools may fail under narrower
ACLs; the server does not expand privileges. There is no arbitrary endpoint tool.

The server assigns the viewer role locally; callers cannot submit a role. Anyone
controlling the process can access its token. This is not a tenant isolation layer.

## Dependencies and references

`requirements.lock` pins runtime dependencies with package hashes. It was resolved
for the tested Python environment; review it when changing Python/platform or SDK.
Installing the local project also needs the declared setuptools build backend.

- [Official MCP SDK](https://github.com/modelcontextprotocol/python-sdk)
- [MCP SDK documentation](https://py.sdk.modelcontextprotocol.io/)
- [Proxmox API viewer](https://pve.proxmox.com/pve-docs/api-viewer/)
- [Proxmox API documentation](https://pve.proxmox.com/wiki/Proxmox_VE_API)
