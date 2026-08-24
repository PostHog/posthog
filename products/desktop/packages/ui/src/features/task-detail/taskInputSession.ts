export const DEFAULT_TASK_INPUT_SESSION_ID = "task-input";

export function getTaskInputSessionId(
  tabId: string | null | undefined,
): string {
  return tabId
    ? `${DEFAULT_TASK_INPUT_SESSION_ID}:${tabId}`
    : DEFAULT_TASK_INPUT_SESSION_ID;
}

export function isTaskInputSessionId(sessionId: string): boolean {
  return (
    sessionId === DEFAULT_TASK_INPUT_SESSION_ID ||
    sessionId.startsWith(`${DEFAULT_TASK_INPUT_SESSION_ID}:`)
  );
}
