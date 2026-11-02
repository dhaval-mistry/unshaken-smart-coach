# Architecture

This directory will contain system diagrams, component boundaries, data-flow
descriptions, and security considerations. The high-level proposal currently
lives in the repository's root README.

- [Local observability design](observability.md): approved Alloy collection and
  Mimir metrics direction with Grafana, Loki, Tempo and OpenTelemetry. Local
  single-process filesystem storage and application-only log collection are approved;
  implementation remains pending.
- [System overview](overview.md): planned components and folder responsibilities.
- [Database design](../database/design.md): tables, relationships and history.
- [Database diagrams](../database/README.md): diagrams matching the design.
- [Initial API design](../api/foundation.md): proposed endpoints and response rules.

## Keeping designs useful

Record design approval, implementation status, related work and open questions
separately. Update designs and diagrams when approved behavior changes. Use a
short [decision record](../decisions/README.md) for important choices that need
an explanation.
