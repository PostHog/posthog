export function isPrivateScoutTrialTool(toolName: unknown): boolean {
    return toolName === 'scout-trial-create' || toolName === 'scout-trial-get'
}
