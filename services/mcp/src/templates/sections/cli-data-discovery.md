**Data discovery:** Before any analytical `call` that touches collected data (`query-*`,
`execute-sql` against `events`/`persons`/`sessions`), confirm the event/property exists via
`call read-data-schema`. Applies to canonical-looking names like `$pageview` too — they vary
per team. If the event isn't in the schema, tell the user instead of querying a guessed name.

Always run `info read-data-schema` first — the recipes below are common cases, not the full schema.

- Events: `call read-data-schema {"query": {"kind": "events"}}` (paginate with `limit`/`offset` if needed). Actions come from `actions-get-all` instead.
- Event properties: `call read-data-schema {"query": {"kind": "event_properties", "event_name": "<event>"}}`
- Person, session, and group properties: `call read-data-schema {"query": {"kind": "entity_properties", "entity": "<entity>"}}` (`entity` is `person`, `session`, or a group type name)
- Values: `call read-data-schema {"query": {"kind": "event_property_values", "event_name": "<event>", "property_name": "<prop>"}}`
