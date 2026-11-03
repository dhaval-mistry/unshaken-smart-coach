# API documentation

Design APIs around what a person is trying to do. A database table does not
automatically need its own create, edit, and delete endpoints.

Design status: **Proposed for review**. Implementation status: **No application
endpoints yet**. The examples below describe planned contracts, not working APIs.

## Designs

| Document | Purpose | Status |
|---|---|---|
| [Initial API design](foundation.md) | User-action map, health checks, and exercise form choices | Proposal; needs human approval before implementation |
| [Workout API design](workouts.md) | Approved timed Bodyweight, complete-template Save, and Cancel outcomes with proposed API contracts | Product choices approved; paths and remaining questions need review; no implementation |

The initial design recommends four read-only endpoints. The separate workout
design covers later owner answers without changing those four endpoints.
Neither document approves unresolved rules in the database design.

The [observability design](../architecture/observability.md) uses Alloy
and Mimir while keeping the shared OpenTelemetry package. It changes future
export destinations and verification, not the API paths or database behavior.

## Keeping contracts consistent

For each approved API story, document the endpoint, input/output examples,
validation, who may access it, error behavior, and required telemetry. Link the
story and relevant database design. Keep secrets and personal data out of
examples. Reuse the implemented FastAPI schema when available instead of
maintaining two conflicting request/response definitions. Review generated
OpenAPI documentation against the approved design in the same change.

The [initial design](foundation.md#common-request-and-response-rules) proposes
shared response, error, request-ID, and access rules. Apply those only after
approval; later designs should reference them instead of copying them.

Start with the [system overview](../architecture/overview.md) and the
[developer reading path](../README.md).
