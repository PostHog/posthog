### Sharing feedback on this MCP server

The `agent-feedback` tool is the primary signal we use to improve tool descriptions, input schemas, response formats, and these instructions for agents like you. We rely on it to find and fix the rough edges you hit in real work.

**When you finish a task on which you hit friction, please call `agent-feedback` before handing back to the user.** Friction means anything that slowed you down or made you guess — examples below. You are not required to call it, and you should skip it for smooth, routine work where nothing stood out. But if something was awkward, missing, or wrong, a short report is the most useful thing you can do for the next agent.

Friction worth reporting (any one is enough):

- A tool description was unclear or ambiguous and you had to guess.
- An input schema was confusing or surprising.
- A response format was hard to consume or contained too much / too little data.
- A tool returned wrong, incomplete, or unexpected results.
- An error message was unhelpful or didn't explain how to recover.
- A capability was missing entirely and you had to work around it.
- These instructions led you down the wrong path.
- A tool worked particularly well — concrete praise is just as useful as criticism.

When you do submit, be specific: quote tool names, parameter names, and error text where possible. Use `task_completed: false` when you couldn't finish the user's request — that signal is at least as valuable as success. Do not include user PII or sensitive query content in any feedback field.

Submitting feedback is **not** a way to end your turn or skip work, and it is **not** a substitute for finishing the user's request. It is a side report to the PostHog team about your experience with the tools — call it once at the end of a task when warranted, then keep going and finish the user's task using the other available tools.
