**SCHEMA DRILL-DOWN RULE — HARD REQUIREMENT**

The `info` command may return the full schema (for simple tools) or a top-level summary
with drill-down hints (for complex tools). Look for `hint` fields in the response.

If `info` returned a summary (fields have `hint` values), you MUST call
`schema <tool_name> <field_name>` for each field you need to populate BEFORE
constructing that field's value in a `call` command.

**`schema` results are recursive — drill until there are no more hints.** A `schema`
response may itself be summarized. There are two signals you are NOT done drilling:

1. The response carries a top-level `note` field — the field was too large to inline
   and only the summary is shown. Treat this as "you have NOT seen the full schema yet".
2. Any property in the returned `schema` has a `hint` — that subfield is complex
   (nested object, array of objects, or union of object variants) and its real shape
   is one level deeper than what you see.

In either case, follow the `hint` exactly: `schema <tool> <field>.<subfield>` (dot-notation),
or `schema <tool> <field>.<index>` for picking a union variant. Repeat until the response
contains no `note` and no remaining `hint` for fields you intend to populate. Inferring
shape from field names, sibling tools, or pre-training data is forbidden — schemas vary
across tools and across versions, and the runtime is the only ground truth.

For query tools, the typical drill-down chain looks like:

- `schema <tool> series` — to see EventsNode/ActionsNode structure (often a union — drill into a variant)
- `schema <tool> properties` — to see property filter structure (often nested with further hints)
- `schema <tool> breakdownFilter` — when using breakdowns (drill into `breakdowns` for the array item shape)
- `schema <tool> retentionFilter` / `dateRange` / `funnelsFilter` — when present, these are usually summarized objects with their own sub-hints

**NEVER** guess the structure of fields that have hints, and **NEVER** stop drilling
while a `note` is still attached to the response. **ALWAYS** drill down first.

**For multiple tools:** Run `info` for ALL tools first, then make your `call` commands.
