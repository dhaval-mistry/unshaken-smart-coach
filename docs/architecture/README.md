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
- [API review map](../api/README.md): all open API issues/#30, baseline versus
  proposed contracts, prerequisites and owner decisions.
- [Exercise API design](../api/exercises.md): private custom creation and
  on-demand stored/provider search with explicit provider-rights gates.
- [Workout API design](../api/workouts.md): template/start/completion/Finish/
  cancellation/history contracts and unresolved mapping/retry choices.

The current application exposes liveness only; database revisions 0001/0002
and the shared telemetry helpers/examples exist. The workout schema follow-up
is proposed, not implemented on main. This design-only review preserves that
boundary and does not accept closed PR #33's implementation.

## Keeping designs useful

Record design approval, implementation status, related work and open questions
separately. Update designs and diagrams when approved behavior changes. Use a
short [decision record](../decisions/README.md) for important choices that need
an explanation.
