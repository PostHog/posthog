export const EXEC_TOOL_NAME = 'exec'

/** Takes the calls a split connection refuses on `exec`, so a client can always allow `exec` and ask on this. */
export const EXEC_WRITE_TOOL_NAME = 'exec-write'

export function isExecDispatcher(toolName: unknown): boolean {
    return toolName === EXEC_TOOL_NAME || toolName === EXEC_WRITE_TOOL_NAME
}
