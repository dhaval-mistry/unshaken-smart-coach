# Database design

Draft for team review. Migration `0001` creates the 13 tables; see [migrations](migrations.md).

- [Detailed design](design.md)
- [Migrations: commands, tests and rollback limits](migrations.md)
- [Rendered ER diagram](er-diagram.md)
- [Mermaid source](er-diagram.mmd)

Resolve the open decisions in design.md before implementing migrations. This package follows the existing PostgreSQL 17 Docker Compose and uv setup.

The design includes confirmed creator-only custom exercises, optional template
updates asked once at workout finish, personal copies for sample-template Yes
answers, separate starting-plan snapshots and actual performance, ad hoc
workouts, and automatic 120-second rest defaults. Technical proposals and
remaining decisions are explicitly marked; this is not migration approval.

