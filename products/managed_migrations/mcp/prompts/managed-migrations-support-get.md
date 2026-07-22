Get one batch import (managed migration) job by id, from any PostHog team, including the raw worker `state` and `import_config` blobs. PostHog staff only: the backend requires a staff user AND a personal API key explicitly carrying the `batch_import_support:read` scope (a full-access `*` key is rejected; OAuth sign-in can never grant it).

Adds to the list fields:

- `state`: the worker-owned progress blob, `{"parts": [{"key", "current_offset", "total_size"}]}`. A part is done when `current_offset >= total_size`; parts are processed in order, so the first unfinished part is the one in flight. `current_offset` is a byte offset into the DECOMPRESSED part - only meaningful against the exact byte stream it was measured on.
- `import_config`: the job's source / data format / sink configuration. It references credentials by secret key NAME only; secret values live in an encrypted column that is never returned by any API.
- `created_by_email`: who started the migration, when known.

Troubleshooting reminders (same semantics as the list tool): `waiting_to_start` = running with no worker lease yet; `lease_expired: true` on a running job = the worker died or the job is about to be re-claimed; a `paused` job keeps its lease and resuming (a Django admin action - this API is read-only) must clear it; `paused` with an invalid-JSON parse error at the resume point usually means the source bytes changed under the committed offset and the in-flight part needs a reset to offset 0 via Django admin's "Resume + re-import in-flight part".
