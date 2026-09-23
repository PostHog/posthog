**Handling errors:**

- If a tool call fails, the error includes a suggestion and similar tool names. Read the suggestion before retrying.
- If a tool name doesn't exist, run `tools` again to find the correct name.
- If no tool covers a PostHog capability the user asks about, don't conclude it doesn't exist — PostHog ships changes daily. {whats_new_check}
