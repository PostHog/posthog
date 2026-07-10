**SCHEMA DRILL-DOWN RULE — HARD REQUIREMENT**

The `info` command may return the full schema (for simple tools) or a top-level summary with drill-down hints (for complex tools). Look for `hint` fields in the response.

If `info` returned a summary (fields have `hint` values), batch every field you need to populate into ONE call — `schema <tool_name> <field1> <field2> ...` (a single field still works) — BEFORE constructing those fields' values in a `call` command. `*` globs expand to sibling fields (e.g. `series.*`).

If `schema` also returns a summary (because the field is too large), drill deeper using dot-notation: `schema <tool> <field>.<subfield>`.

**NEVER** guess the structure of fields that have hints. **ALWAYS** drill down first.

For query tools, batch the fields you need in a single call, e.g.:

- `schema <tool> series series.properties breakdownFilter` — the item (EventsNode/ActionsNode) structure, the series property-filter shape, and the breakdown config in one response

**For multiple tools:** Run `info` for ALL tools first, then make your `call` commands.
