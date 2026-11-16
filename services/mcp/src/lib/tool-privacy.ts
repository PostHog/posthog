export function isPrivateScoutTrialTool(toolName: unknown): boolean {
    return typeof toolName === 'string' && (toolName.startsWith('scout-trial-') || toolName.startsWith('scout-rubric-'))
}

export function hasSqlFilters(toolName: string, input: unknown): boolean {
    const sqlInput = input as { filters?: unknown; command?: unknown; tool?: unknown } | null | undefined
    // Wrappers can repair or embed arguments, so treat their SQL calls as potentially filtered.
    return (
        (toolName === 'execute-sql' && sqlInput?.filters != null) ||
        (toolName === 'posthog-connection-call' && sqlInput?.tool === 'execute-sql') ||
        (toolName === 'exec' && typeof sqlInput?.command === 'string' && sqlInput.command.includes('execute-sql'))
    )
}
