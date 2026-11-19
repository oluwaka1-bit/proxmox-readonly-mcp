# Release checks

Version 0.2.0 was verified on Python 3.13.18 with MCP SDK 2.2.0 and
setuptools 84.2.1. A clean environment installed the 29 hash-locked packages
and built the project. The installed command started and the SDK example
negotiated MCP over local stdio, listed eight tools and returned fictional
guests. All 37 tests passed with no skips.

Test coverage includes the default mock backend and an injected transport for
the opt-in HTTPS adapter. Compatibility with a live cluster, its token ACLs
and its certificate provisioning remains unverified.

See [security checks](SECURITY_REVIEW.md), [dependency inventory](DEPENDENCIES.md),
[capabilities and limits](../docs/CLAIMS.md), and [usage](../docs/USAGE.md).
