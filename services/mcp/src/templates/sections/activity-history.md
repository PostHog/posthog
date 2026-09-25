### Activity history

Use `advanced-activity-logs-list` for configuration history. Read its schema once before the first history check, then pass `start_date`, `end_date`, relevant `scopes`/`item_ids`, `page_size: 10`, and only needed `fields`. Request `detail.changes` only for a specific candidate. A non-null `next` means incomplete history; narrow the window or paginate with `page` within the investigation budget before ruling out an edit.

To audit a scout run, bracket its start and completion times and filter `clients: ["mcp"]`. Include `Notebook` alongside the resource types covered by its write grant. Read the actors from the results: the same window can include the acting user's other MCP writes.

Access controls and the plan's retention window still apply. If access is denied, stop history checks for the run and record the limitation. Missing history does not prove that no configuration change occurred.
