# Database design

Design status: **Technical proposal for human review**. Database stories and
master-record names/order are already approved; this revision records the
owner's specific answers and proposes the concrete representation. No schema,
migrations, application code, or database changes are included.

- [Detailed design and owner answers](design.md)
- [Rendered ER diagram](er-diagram.md)
- [Matching Mermaid source](er-diagram.mmd)

Confirmed first-version behavior includes time/distance tracking: Cardio needs
duration and distance; Duration needs duration; other categories need reps.
Weight remains optional. At most one workout per user may be in progress.

Permanent live-source/unperformed-set deletion must preserve original starting
plan and completed history. Completed-set/workout permanent deletion is not
a version-one feature. The draft proposes immutable initial JSON and original
UUIDs with nullable live links, keeping 13 tables. Review the exact snapshot,
measurement, live-plan and deletion guard rules before calling #2 complete.

After human review, #3 creates versioned tables/guards and #4 installs the
approved stable master data. Preserve PostgreSQL 17 in root Compose, the private
root environment conventions, and one uv backend project. Never apply migrations
to an existing/shared database without approval of its identified target.

