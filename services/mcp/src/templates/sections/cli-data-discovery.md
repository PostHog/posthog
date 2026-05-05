**Data discovery:** Before any analytical `call` that touches collected data (`query-*`,
`execute-sql` against `events`/`persons`/`sessions`), confirm the event/property exists via
`call read-data-schema`. Applies to canonical-looking names like `$pageview` too — they vary
per team. If the event isn't in the schema, tell the user instead of querying a guessed name.

Always run `info read-data-schema` first — the recipes below are common cases, not the full schema. Each `kind` accepts a different set of params; do not invent params (e.g. `search`) that the schema does not declare. If you need to filter, page through results and filter client-side.

- Events: `call read-data-schema` with `input: { "query": { "kind": "events" } }` (paginate with `limit`/`offset` if needed)
- Properties: `call read-data-schema` with `input: { "query": { "kind": "event_properties", "event_name": "<event>" } }`
- Values: `call read-data-schema` with `input: { "query": { "kind": "event_property_values", "event_name": "<event>", "property_name": "<prop>" } }`
