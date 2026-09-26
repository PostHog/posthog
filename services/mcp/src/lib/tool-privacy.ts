export function isPrivateScoutTrialTool(toolName: unknown): boolean {
    return toolName === 'scout-trial-create' || toolName === 'scout-trial-get'
}

const TASK_CONTENT_READ_TOOLS = new Set([
    'tasks-list',
    'tasks-retrieve',
    'tasks-runs-list',
    'tasks-runs-retrieve',
    'tasks-runs-session-logs-retrieve',
    'tasks-artifacts-list',
    'tasks-runs-artifacts-download-create',
    'tasks-runs-artifacts-download-retrieve',
    'tasks-runs-living-artifacts-list',
    'tasks-runs-living-artifacts-open',
    'tasks-runs-task-session-retrieve',
])

export function isTaskContentReadTool(toolName: unknown): boolean {
    return typeof toolName === 'string' && TASK_CONTENT_READ_TOOLS.has(toolName)
}
