import { ApiError } from 'lib/api'

export interface SendFailure {
    /** The command never reached the agent, so a resend is safe. Transport faults and 5xx qualify. */
    retryable: boolean
    /** What to show the user — the backend cause when it gave one, else the caller's fallback. */
    message: string
}

/**
 * Classify a failed run command send.
 *
 * The tasks command endpoint already reports the cause: a 4xx carries a run- or sandbox-state error
 * the user must act on (`No active sandbox for this task run`, `Task run workflow has ended`), while a
 * transport fault or 5xx means the command did not land. This mirrors the backend command classifier
 * (`products/tasks/backend/logic/services/agent_command.py`), where 5xx and lost connections are
 * retryable and a client rejection is not.
 */
export function classifySendFailure(error: unknown, fallback: string): SendFailure {
    if (error instanceof ApiError) {
        const cause = typeof error.data?.error === 'string' && error.data.error ? error.data.error : error.detail
        // No status means the request never reached the server (a NetworkError); treat it as transient.
        const retryable = error.status === undefined || error.status >= 500
        return { retryable, message: cause ?? fallback }
    }
    return { retryable: false, message: fallback }
}
