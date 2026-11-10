## Workflow: review configured sources

When the user asks "which signal sources are set up?" or "is <product> hooked up?":

```json
inbox-source-configs-list
{ "limit": 50 }
```

Each entry returns `id`, `source_product`, `source_type`, `enabled`, `status`, plus timestamps.
For full details (including the per-source `config` JSON — recording filters, evaluation IDs,
etc.):

```json
inbox-source-configs-retrieve
{ "id": "<source_config_uuid>" }
```

Integration credentials live in a separate `Integration` model — they are **not** in the
`config` blob, so it's safe to summarize the contents back to the user.

The `status` field reflects the underlying data import or workflow:

- `running` / `completed` — feeding signals normally
- `failed` — the source isn't currently producing signals; flag this to the user

To turn a source on or off, use `inbox-source-configs-partial-update` with the config's `id` and
`{ "enabled": true | false }` — only the fields you pass change, so this is the right tool for a
plain toggle (`-update` replaces the whole record; `-create` stands up a new source). Confirm with
the user before flipping a source, since enabling one drives signal processing and spend.

```json
inbox-source-configs-partial-update
{ "id": "<source_config_uuid>", "enabled": false }
```

To edit individual source settings, send only the top-level keys to change in `config_set` and keys to delete in `config_remove`.
These edits preserve unrelated settings even when another editor saves at the same time.
For guidance, set `config_set.steering` and include `default_not_actionable` in `config_remove`.
Use `config_set.linear_team_ids` for Linear team selection.
Reserve `config` for an intentional whole-object replacement; do not combine it with key edits.
