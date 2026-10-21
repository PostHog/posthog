export function mcpAnalyticsSetupPrompt(projectId: number, appUrl: string): string {
    const projectUrl = new URL(`/project/${projectId}/mcp-analytics/activity`, appUrl).href

    return `Install PostHog MCP analytics in the MCP server in this repository.
Target PostHog project ${projectId} at ${appUrl}.
Read https://posthog.com/docs/mcp-analytics/installation.md first and follow the instructions for this server's language, framework, and SDK version.

Locate the existing MCP server entry point before editing. If you cannot find a server, explain which directories you checked and ask me for the correct directory. This task instruments my server; it does not install the PostHog MCP connector or create a new server.

Confirm the matching ingestion host and project token. Use the repository's environment configuration for credentials; ask me for missing configuration without putting secrets in source code or terminal output.

Make the smallest necessary change, including flushing events correctly for this runtime. Run the relevant checks, then help me invoke an existing safe, read-only tool. Verify that its $mcp_tool_call arrives in the target project and comes from the server you instrumented. An initialize event is optional and is not enough to verify installation.

Open ${projectUrl} to inspect the call. If you cannot access the project, give me the verification steps and mark verification as pending. Report the files changed and any remaining restart or deployment steps. Only report verification as complete after the tool-call event is observed.`
}
