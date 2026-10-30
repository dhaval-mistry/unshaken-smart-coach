# Documentation

Start here before writing code or fixing a bug. A design explains what we plan
to build. A setup guide explains how to run what actually exists. Approval of a
design does not mean the code is implemented or tested.

## Before starting a story

1. Read the GitHub issue, acceptance criteria, and relevant discussions. For a
   bug, read the reproduction steps and identify the affected commit.
2. Read the root [repository instructions](../AGENTS.md).
3. Read the [system overview](architecture/overview.md) and the relevant design
   listed in the [architecture index](architecture/README.md).
4. Check design status and open questions. Preserve recorded approvals. Ask
   about missing product rules; recommend routine engineering choices using
   existing conventions.
5. Read the relevant [setup guide](setup/README.md), then inspect actual code
   and tests. Do not assume a planned file or command already exists.
6. Implement only the agreed scope. In the PR, link the issue and design,
   explain how the acceptance criteria were checked, and update affected docs.

Example: a story about recording workout sets needs the database design for
ownership and history rules, and the observability design for safe logs and
traces. Installing Grafana alone does not decide either feature's behavior.

## Where information belongs

- [`setup/`](setup/README.md): local installation and development environment guides.
- [`architecture/`](architecture/README.md): system design and component boundaries.
- [`database/`](database/README.md): table definitions, data rules, and ER diagrams.
- [`api/`](api/README.md): API contracts and examples.
- [`decisions/`](decisions/README.md): architecture decision records (ADRs).

Keep one maintained home for each design. GitHub holds the task discussion,
approval, progress, and test evidence. Issues should link the relevant document
and summarize what matters for that task, rather than maintain a second full
design. Resolve contradictions explicitly; do not silently choose whichever
source is easier to implement.
