# Topics

A Meep topic groups a mission, goals, rules, facts, files, board tasks, and a conversation for one project member. The desktop stores a local replica so a person can work offline. On reconnect it submits queued commands to the authenticated Meep product API. Django validates ownership, applies the shared topic transitions, and records each command's revision and receipt. A retry with the same command ID cannot apply the command twice.

The topic sidebar shows the topic’s icon and name, with a one-line preview and date for its latest message or task result. Click the icon next to the topic name in the main pane to choose a hedgehog and background color.

PostHog Tasks runs topic chat, board investigations, and view authoring. On a task created from topic chat, select **Original request** to jump to the message that started it. A scoped task can read its assigned topic through PostHog MCP. A request for ongoing monitoring creates a native Scout linked to that topic. The desktop can read its findings through topic sync and the agent can read them through topic get. Use a routine for an explicitly requested deterministic workflow.

Connect your GitHub account from **Settings → General → Connect GitHub** once for all your topics. Finish authorization in PostHog, then return to Meep. Topic chat can look up your repositories and investigate one in a read-only task, including in topics created before you connected. If chat suggests saving a repository for future questions, review the suggestion in **Needs you**. You can also choose or change the saved repository from **Linked** in the overview. All overview sections open even when empty. Removing a saved repository keeps your GitHub account connected.

The native workspace uses fixture hosts to exercise topic state, connector behavior, and rendering without a signed-in project. Run `sh scripts/check.sh` from the workspace to verify its crates. See the [product guide](../../README.md) for startup and the [MCP capability design](../../MCP.md) for tool contracts and remaining features.
