### Discovering the SDK surface (`types`)

`types` picks its mode by exactness:

- **Exact fetch** — when every token names an exact symbol (`types FeatureFlag`, `types featureFlags.update FeatureFlagsUpdateParams`, `types surveys`), you get exactly those full TS declarations: methods with their description, types as full interfaces, domains as a signature list. Referenced types come back as a hint line (`References — run "types …"`) instead of being inlined — follow it rather than guessing nested shapes.
- **Search** — anything else is one case-insensitive pattern (regex or plain substring) over method ids, signatures, titles, descriptions, and type names: `types funnel`, `types create.*dashboard`. Results are one-line signatures grouped by category.

Signatures are scope-annotated for the current credentials (`[requires feature_flag:write ✓]` vs `— missing on this token`) — check the annotation before writing a mutation script. Output is char-capped: a truncation names the exact follow-up `types` call, so never act on a cut-off declaration.

Workflow: search once to find the method, fetch its params type, then write the script. Params and response shapes come from `types` — constructing them from memory is guessing.
