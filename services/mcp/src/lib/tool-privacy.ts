export function isPrivateScoutTrialTool(toolName: unknown): boolean {
    return typeof toolName === 'string' && (toolName.startsWith('scout-trial-') || toolName.startsWith('scout-rubric-'))
}

export function hasSqlFilters(toolName: string, input: unknown): boolean {
    const sqlInput = input as { filters?: unknown; command?: unknown } | null | undefined
    // Exec embeds arguments in text, so treat every SQL exec command as potentially filtered.
    return (
        (toolName === 'execute-sql' && sqlInput?.filters != null) ||
        (toolName === 'exec' && typeof sqlInput?.command === 'string' && sqlInput.command.includes('execute-sql'))
    )
}
