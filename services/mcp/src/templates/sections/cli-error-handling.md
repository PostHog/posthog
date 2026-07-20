**Handling errors:**

- If a tool call fails, the error includes a suggestion and similar tool names. Read the suggestion before retrying.
- If a tool name doesn't exist, run `search <term>` to find the current name before claiming the capability is unavailable.
- If a tool is hidden by missing scopes, reconnect or reauthorize the MCP connection. Logging in through browser automation does not update MCP permissions.
