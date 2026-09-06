### Reporting a missing capability

The `report-missing-capability` tool records a capability this MCP server does not have. Call it when you go looking for a tool, an argument, or a field that would let you finish the user's request, and there is none — after you have searched the tool catalog, not instead of searching it.

Put what you wanted to do in `description`, in your own words: the task you could not finish, and the shape of the data or action you needed. Name the capability rather than the tool name you guessed at. Keep it to a sentence or two, and leave out user PII and sensitive query content.

Reports land on the missing capabilities feed in MCP analytics, which the PostHog team reads to decide what to build next. Use `agent-feedback` instead when the tool exists but disappointed you — wrong results, an unclear description, a confusing schema, an unhelpful error.

Reporting a gap is not a way to end your turn. Report it, then finish the user's task with the tools you do have.
