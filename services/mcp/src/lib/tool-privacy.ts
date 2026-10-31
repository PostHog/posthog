export function isPrivateScoutTrialTool(toolName: unknown): boolean {
    return typeof toolName === 'string' && (toolName.startsWith('scout-trial-') || toolName.startsWith('scout-rubric-'))
}
