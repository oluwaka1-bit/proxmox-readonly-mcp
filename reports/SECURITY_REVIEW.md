# Security checks

The test suite exercises real local MCP stdio and injects HTTPS responses for
adapter tests. Checks cover strict tool arguments, a fixed viewer role, startup
configuration, protocol-only stdout, TLS verification, credential-file access,
fixed GET routes, node and guest scope, proxy isolation, redirect refusal,
bounded response bodies and sanitized errors.

`pip-audit` 2.10.1 found no known vulnerabilities in the 29 locked packages
at verification time.

Access to the local process and its launch configuration is the trust boundary.
Read-only annotations are advisory. Enforce read-only permissions in Proxmox
with a dedicated token. Field allowlists do not anonymize returned values, and
bounded inventories may be incomplete. Proving backup recovery requires a test
restore. See the [security policy](../SECURITY.md) for reporting.
