**SCHEMA DRILL-DOWN RULE — HARD REQUIREMENT**

The `info` command may return the full schema (for simple tools) or a top-level summary with drill-down hints (for complex tools). Look for `hint` fields in the response.

If `info` returned a summary (fields have `hint` values), call `schema <tool_name> <field_name>` for each field you need to populate BEFORE constructing that field's value in a `call` command.

If `schema` also returns a summary (because the field is too large), drill deeper using dot-notation: `schema <tool> <field>.<subfield>`.

**NEVER** guess the structure of fields that have hints. **ALWAYS** drill down first.

For query tools, you will typically need:

- `schema <tool> series` — to see EventsNode/ActionsNode structure
- `schema <tool> series.properties` — to see property filter structure of series

**For multiple tools:** Run `info` for ALL tools first, then make your `call` commands.
