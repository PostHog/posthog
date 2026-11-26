# The attempt ID is a create-only column on `HogFlow`

A messaging call to action mints an attempt ID when it is shown, and the workflow saves it once, at its first save, as `HogFlow.entry_attempt_id`, a nullable UUID that the serializer accepts only on create, like `source_record`.
We considered keeping attribution in `entry_source`, but `entry_source` lives in `sessionStorage` and is gone by the next session, long before a workflow sends.
We considered a JSON field with the placement, variant and attempt, but the `messaging cta shown` event already holds the placement and variant for each attempt, so the column only needs the join key.
We considered reusing `source_record`, but it names the record a workflow started from, such as a cohort, and many attempts can start from one record.

## Consequences

Analysis joins `messaging cta shown` to `hog_flow_created` and `workflow first real send` on the attempt ID.
Workflows created before the column, and workflows created from entry points without an attempt, keep it null.
See `docs/architecture/messaging-cta-slot.md`.
