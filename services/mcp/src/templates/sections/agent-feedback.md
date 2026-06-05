### Sharing feedback on this MCP server

The `agent-feedback` tool is the primary signal we use to improve this MCP server — its tool descriptions, input schemas, response formats, and these instructions. Keep every report strictly about the MCP server itself, not about the user's task, their data, or your findings.

**When you finish a task on which you hit friction with the MCP, call `agent-feedback` before handing back to the user.** Skip it for smooth, routine work where nothing stood out.

Keep it short: give a one-sentence `summary`, then write the detail fields (`friction_points`, `suggested_improvement`, `details`) as clear, concise bullet points, quoting the exact tool name, parameter, or error text. Friction worth reporting (any one is enough):

- A tool description was unclear or ambiguous and you had to guess.
- An input schema was confusing or surprising.
- A response format was hard to consume or had too much / too little data.
- A tool returned wrong, incomplete, or unexpected results.
- An error message was unhelpful or didn't explain how to recover.
- A capability was missing entirely and you had to work around it.
- These instructions led you down the wrong path.
- A tool worked particularly well — concrete praise is just as useful as criticism.

Use `task_completed: false` when you couldn't finish the user's request — that signal is at least as valuable as success. Do not include user PII or sensitive query content in any field.

Submitting feedback is **not** a way to end your turn or skip work. It is a side report to the PostHog team about the MCP server — call it once at the end of a task when warranted, then keep going and finish the user's task with the other tools.
