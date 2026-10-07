// pinned: storage key, a rename would forget which workflow the first run created
const FIRST_RUN_WORKFLOW_KEY = 'workflows-first-run-workflow-id'

export function rememberFirstRunWorkflow(workflowId: string): void {
    try {
        window.localStorage.setItem(FIRST_RUN_WORKFLOW_KEY, workflowId)
    } catch {
        // Storage can be full or blocked; the first run still works without the memory.
    }
}

export function getFirstRunWorkflowId(): string | null {
    try {
        return window.localStorage.getItem(FIRST_RUN_WORKFLOW_KEY)
    } catch {
        return null
    }
}
