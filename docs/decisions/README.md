# Architecture decisions

Important technical choices will be recorded here as architecture decision
records (ADRs). Each record should explain its context, decision, consequences,
and status.

Use these short records only for important choices with alternatives or lasting
effects, such as changing the metrics storage tool. A new helper function does
not need its own record.

For a new decision, use a short numbered file such as `0001-short-topic.md`:

1. Status: Proposed, Accepted, or Superseded.
2. Context: the problem we need to solve.
3. Decision: what is proposed or approved, and a link to the human approval.
4. Alternatives: what else was considered and why it was not chosen.
5. Effects: benefits, limits, and required follow-up work.
6. Related design, issue, and PR links.

Keep the current design in its normal architecture/database/API document. Link
it here rather than copying it. When a decision changes, retain the old record
and link its replacement so the reason for the change is not lost. Do not label
a proposal Accepted without recorded human approval.
