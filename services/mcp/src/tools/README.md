# Hand-written tools

This guide covers hand-written tools only.
Most tools are generated from `products/<product>/mcp/tools.yaml`.
For those, follow the [implementing MCP tools skill](../../../../.agents/skills/implementing-mcp-tools/SKILL.md) and the [handbook guide](../../../../docs/published/handbook/engineering/ai/implementing-mcp-tools.md).

To change a generated tool's request or error handling, use `hooks:` in its tools.yaml instead of a hand-written tool with the same name.
Write a tool by hand only when codegen cannot express it.
Examples are tools that call several endpoints or reshape the response.
Existing hand-written tools live in the folders next to this file, for example `featureFlags/`.

## Quick start

1. Create the handler.
   Export a factory that returns a `ToolBase` (see `types.ts`).
   Copy the structure of a nearby hand-written tool.
2. Register the factory in `TOOL_MAP` in `index.ts`.
3. Add the definition to `schema/tool-definitions.json`.
4. Add unit tests under `services/mcp/tests/unit/`.

The factory returns the name, input schema, and handler.
Title, description, scopes, and annotations come from the JSON definition.

### Tool definition

Each entry in `schema/tool-definitions.json` needs a clear description, a feature, the required scopes, and annotations:

```json
{
  "my-tool-name": {
    "title": "My tool",
    "description": "What the tool does and what the agent should do next.",
    "category": "Feature flags",
    "feature": "flags",
    "summary": "One-line summary for the docs.",
    "required_scopes": ["feature_flag:read"],
    "annotations": {
      "destructiveHint": false,
      "idempotentHint": true,
      "openWorldHint": true,
      "readOnlyHint": true
    }
  }
}
```

- `feature` must be lowercase snake_case (for example `error_tracking`).
  `scripts/yaml-config-schema.ts` defines the rule.
- Use the highest scope the tool needs: write if it changes data, read if it only reads.
- `category` and `summary` appear in the docs.
  The MCP client does not read them.
- Tool names are lowercase kebab-case.

If you add a new feature, also list it in the feature list in `services/mcp/README.md` and add it to `tests/unit/tool-filtering.test.ts`.

## Schema Design Philosophy

### Input Schemas

- **Be strict**: Validate inputs thoroughly to catch errors early
- **Be user-friendly**: Design inputs around what users naturally want to provide
- **Be minimal**: Only require essential fields, make others optional
- **Be clear**: Use descriptive names that don't require API knowledge

### Output Schemas

- **Be permissive**: Don't fail on unexpected fields from the API
- **Be comprehensive**: Include useful information in responses, but don't stuff the context window with unnecessary information
- **Add context**: Include helpful URLs, descriptions, or related data
- **Be consistent**: Use similar patterns across tools
