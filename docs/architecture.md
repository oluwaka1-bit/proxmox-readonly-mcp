# Architecture and trust boundaries

```mermaid
flowchart LR
  subgraph Host[Trusted local host boundary]
    C[MCP host or SDK client]
    S[SDK stdio server]
    R[Strict tool registry]
    C <-->|MCP initialization and calls| S
    S -->|Fixed viewer role| R
  end
  R -->|Default mock| M[Fictional fixtures]
  subgraph Live[Explicit live backend boundary]
    A[Fixed GET HTTPS adapter]
    F[Owner-only token file]
    T[Verified TLS and node/guest scope]
    F --> A --> T
  end
  R -->|Explicit startup choice| A
  T --> P[User configured Proxmox API with read-only ACLs]
  M --> O[Bounded field projection]
  P --> O --> S
```

The MCP transport is real local stdio; the demonstration backend is fictional.
The live adapter is implemented and tested with injected responses, without a
verified real-cluster deployment. No remote MCP endpoint or user authentication
service is included. The trusted host controls process launch and startup settings.

Tools accept only declared arguments. Fixed GET routes narrow behavior independently
of advisory MCP read-only annotations. Explicit upstream token ACLs are still needed.
TLS uses chain and hostname verification; cluster-specific insecure exceptions are
not included. Redirects are refused to keep tokens bound to the configured origin.

Field projection limits the fields returned. Real values can still contain
sensitive information. Review local output before sharing it. Backup recovery
requires a successful restore test.
