# Architecture

This directory will contain system diagrams, component boundaries, data-flow
descriptions, and security considerations. The high-level proposal currently
lives in the repository's root README.

- [Local observability design](observability.md): approved Alloy collection and
  Mimir metrics direction with Grafana, Loki, Tempo and OpenTelemetry. Local
  single-process filesystem storage and application-only log collection are
  approved; the local stack and shared telemetry package are implemented.
- [System overview](overview.md): planned components and folder responsibilities.
- [Local backend container design](backend-container.md): owner-approved
  immutable Python 3.12 image, Compose service, configuration boundaries,
  explicit migrations and verification; not implemented.
- [Database design](../database/design.md): tables, relationships and history.
- [Database diagrams](../database/README.md): diagrams matching the design.
- [Initial API design](../api/foundation.md): proposed endpoints and response rules.
- [API review map](../api/README.md): all open API issues/#30, baseline versus
  proposed contracts, prerequisites and owner decisions.
- [Exercise API design](../api/exercises.md): private custom creation and
  on-demand stored/provider search with explicit provider-rights gates.
- [Workout API design](../api/workouts.md): template/start/completion/Finish/
  cancellation/history contracts and unresolved mapping/retry choices.

The current application exposes liveness and readiness (`/health/live` and
`/health/ready`); database revisions 0001–0003 and
the shared telemetry helpers/examples exist. PR #37 implemented the approved
workout schema follow-up on main; product workout APIs remain unimplemented.
PostgreSQL and the optional observability stack have Compose services, but the
FastAPI backend does not yet have a Dockerfile or Compose service.

## Keeping designs useful

Record design approval, implementation status, related work and open questions
separately. Update designs and diagrams when approved behavior changes. Use a
short [decision record](../decisions/README.md) for important choices that need
an explanation.
