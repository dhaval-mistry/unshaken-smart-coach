# Architecture

Use this index to find the design for a story before changing code. Read the
[developer reading path](../README.md) first if you are new to the project.

| Document | What it covers | Design status | Implementation status |
|---|---|---|---|
| [System overview](overview.md) | Components, folders, and shared-code boundaries | Agreed direction; feature details follow their own approvals | Application not started |
| [Database design](../database/design.md) | Tables, relationships, ownership, and history | Draft with confirmed rules and remaining decisions; see issue #2 | No migrations or models yet |
| [Database diagrams](../database/README.md) | Matching Mermaid source and rendered diagram | Follow the database design status | Documentation only |
| [Observability design](observability.md) | Shared OpenTelemetry, Alloy, Mimir, Loki, Tempo, and Grafana | Alloy/Mimir revision proposed; earlier Collector/Prometheus approval and retention retained in the record; see issues #7-#15 | Stack and shared package not started |
| [Initial API design](../api/foundation.md) | User actions, health checks, form choices, and response rules | Proposed for review; access policy and scope need approval | No application endpoints yet |

## Keeping designs useful

At the top of a design, record these separately:

- **Design status:** Draft, Approved, or Superseded (replaced by another design).
- **Implementation status:** Not started, Partial, or Implemented with evidence.
- **Related work:** GitHub issue/PR links and the recorded approval.
- **Open questions:** Decisions still needed; do not implement them silently.

For a partially approved design, name exactly which parts are approved. Updating
documentation does not close an issue or prove a feature works. When code is
merged, update the status with the PR/commit and validation evidence.

Use a short [decision record](../decisions/README.md) only for important choices
that need an explanation of why. Do not create a new document for every small
implementation detail.
