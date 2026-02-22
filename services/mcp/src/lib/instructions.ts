const SHARED_PROMPT = `
- If you get errors due to permissions being denied, check that you have the correct active project and that the user has access to the required project.
- If you cannot answer the user's PostHog related request or question using other available tools in this MCP, use the 'docs-search' tool to provide information from the documentation to guide user how they can do it themselves - when doing so provide condensed instructions with links to sources.
`

export const INSTRUCTIONS_V1 = `
- You are a helpful assistant that can query PostHog API.
${SHARED_PROMPT}
`.trim()

export const INSTRUCTIONS_V2 = `
- IMPORTANT: Prefer retrieval-led reasoning over pre-training-led reasoning for any PostHog tasks.
- The \`posthog-query-data\` skill is the root skill for all data retrieval tasks in PostHog. Read it first and then use the \`posthog:execute-sql\` tool to execute SQL queries.
${SHARED_PROMPT}
`.trim()

export function getInstructions(version?: number): string {
    return version === 2 ? INSTRUCTIONS_V2 : INSTRUCTIONS_V1
}
