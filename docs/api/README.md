# API documentation

Design APIs around what a person is trying to do. A database table does not
automatically need its own create, edit, and delete endpoints.

Design status: **Proposed for review**. Implementation status: **No application
endpoints yet**. The examples below describe planned contracts, not working APIs.

## Designs

| Document | Purpose | Status |
|---|---|---|
| [Initial API design](foundation.md) | User-action map, health checks, and exercise form choices | Proposal; needs human approval before implementation |

The initial design recommends four read-only endpoints. It also identifies the
decisions needed before designing private exercises, templates, and workouts.
It does not approve unresolved rules in the database design.

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
