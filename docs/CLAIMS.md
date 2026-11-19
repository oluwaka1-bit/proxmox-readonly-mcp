# Capabilities and evidence

| Capability | Fresh public candidate evidence | Limits |
|---|---|---|
| MCP protocol | Official SDK stdio initialization, discovery and eight tool calls tested | Local process only; no remote MCP service |
| API access | Fixed GET HTTPS route mapping and mock transport tested | No live-cluster compatibility test |
| Node and guest scope | Configured node and allowed guest IDs enforced in fake-response tests | Upstream token ACLs also required; empty guest scope denies guest reads |
| Storage, jobs, tasks, snapshots, firewall | Mapped and filtered synthetic responses | Broad jobs omitted; metadata is not restore proof |
| Authentication | Token-file format, owner/mode, final symlink checks tested | Local host is trusted; no remote user authentication |
| TLS | Verified chain/hostname contexts and optional CA loading tested | No real-cluster certificate handshake |
| Validation/errors | Invalid inputs, bounded JSON, redirects, safe names and fixed errors tested | Semantic schema coverage remains limited |
| Dependencies | Hash-pinned 29-package runtime/build graph audited | No known findings at audit time is not a security guarantee |

See the [release checks](../reports/READINESS.md) for the tested Python and SDK
versions. Tests cover injected HTTPS responses, real local stdio subprocesses
and the shared tool contracts. Production deployment health, benchmark performance
and restore success remain unverified.
