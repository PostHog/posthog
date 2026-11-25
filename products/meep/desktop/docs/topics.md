# Topics

A Meep topic groups a mission, goals, rules, facts, files, board tasks, and a conversation for one project member. The desktop stores a local replica so a person can work offline. On reconnect it submits queued commands to the authenticated Meep product API. Django validates ownership, applies the shared topic transitions, and records each command's revision and receipt. A retry with the same command ID cannot apply the command twice.

PostHog Tasks runs topic chat, board investigations, and view authoring. A scoped task can read its assigned topic through PostHog MCP. A request for ongoing monitoring creates a native Scout linked to that topic. The desktop can read its findings through topic sync and the agent can read them through topic get. Use a routine for an explicitly requested deterministic workflow.

The native workspace uses fixture hosts to exercise topic state, connector behavior, and rendering without a signed-in project. Run `sh scripts/check.sh` from the workspace to verify its crates. See the [product guide](../../README.md) for startup and the [MCP capability design](../../MCP.md) for tool contracts and remaining features.
