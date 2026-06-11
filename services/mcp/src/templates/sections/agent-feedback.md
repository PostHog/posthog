### Sharing feedback on this MCP server

The `agent-feedback` tool is the primary signal we use to fix problems with this MCP server — its tool descriptions, input schemas, response formats, and these instructions. Keep every report strictly about the MCP server itself, not about the user's task, their data, or your findings.

**Only call `agent-feedback` when something went wrong or was missing with the MCP — report problems, not praise.** The feedback must be constructive and actionable: each report should point at a concrete defect the PostHog team can fix. Skip it entirely for smooth, routine work — do **not** submit positive or "everything worked fine" reports, as they are noise we cannot act on.

Keep it short: give a one-sentence `summary`, then write the detail fields (`friction_points`, `suggested_improvement`, `details`) as clear, concise bullet points, quoting the exact tool name, parameter, or error text. Report only when one of these actually happened:

- A tool description was unclear or ambiguous and you had to guess.
- An input schema was confusing or surprising.
- A response format was hard to consume or had too much / too little data.
- A tool returned wrong, incomplete, or unexpected results.
- An error message was unhelpful or didn't explain how to recover.
- A capability was missing entirely and you had to work around it.
- These instructions led you down the wrong path.

Every report must include a concrete `suggested_improvement` — if you can't name a specific change the team should make, don't submit. Use `task_completed: false` when you couldn't finish the user's request — that signal is especially valuable. Do not include user PII or sensitive query content in any field.

Submitting feedback is **not** a way to end your turn or skip work. It is a side report to the PostHog team about the MCP server — call it once at the end of a task when warranted, then keep going and finish the user's task with the other tools.
