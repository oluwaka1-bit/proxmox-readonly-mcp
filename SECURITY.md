# Security policy

Mock mode is the default and uses fictional data without credentials or network calls.
Live mode is an explicit integration option for the user's approved infrastructure;
it has offline tests but no real-cluster compatibility or deployment assessment.

Restrict access to the stdio process and its startup configuration. Use a dedicated
privilege-separated token with minimum read permissions. Protect the token file
with owner-only access and trust certificate chains and hostnames. Do not disable
verification or grant broader rights to silence an error. The upstream API must
enforce permissions independently of tool annotations and this reference's checks.

Real response strings can disclose private inventory despite field projection.
Do not commit tokens, environment settings, responses, logs or screenshots. Review
all candidate contents and dependency notices before publishing. Automated scans
cannot guarantee sanitization or license compliance.

Use [GitHub private vulnerability reporting](https://github.com/oluwaka1-bit/proxmox-readonly-mcp/security/advisories/new)
for suspected vulnerabilities. Include the affected version, sanitized reproduction
steps, and expected and actual behavior. Keep credentials and operational details
out of public issues.
