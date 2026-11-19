export const EXEC_TOOL_NAME = 'exec'

/** Refuses every write on every request, so a client can always allow it without the server tracking any state. */
export const EXEC_READ_TOOL_NAME = 'exec-read'

export const EXEC_WRITE_TOOL_NAME = 'exec-write'

export function isExecDispatcher(toolName: unknown): boolean {
    return toolName === EXEC_TOOL_NAME || toolName === EXEC_READ_TOOL_NAME || toolName === EXEC_WRITE_TOOL_NAME
}
