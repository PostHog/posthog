import { router } from 'kea-router'

import { ApiError } from 'lib/api-error'
import { urls } from 'scenes/urls'

/** Which of the two composer calls failed, so the toast can name the step. */
export type TaskSubmitStep = 'create' | 'run'

/** Optional action rendered as a button on the failure toast. */
export interface TaskSubmitErrorAction {
    label: string
    action: () => void
}

export interface TaskSubmitErrorInfo {
    message: string
    button?: TaskSubmitErrorAction
}

// Backend refusal codes the composer routes to a next step instead of a dead toast.
// See products/tasks/backend/logic/services/code_usage_gate.py and compute_quota.py.
const BILLING_LIMIT_CODES = new Set([
    'posthog_code_billing_limit_exceeded',
    'organization_deactivated',
    'usage_limit_exceeded',
])
const CODE_ACCESS_REQUIRED_CODE = 'code_access_required'

function backendMessage(error: ApiError): string | null {
    // fromResponse sets `message` to the backend `error`/`detail`/`message` string; `data.error` is the raw body.
    const fromData = typeof error.data?.error === 'string' ? error.data.error : null
    return fromData || error.detail || error.message || null
}

function fallbackMessage(step: TaskSubmitStep): string {
    return step === 'create'
        ? 'Could not create the task. Please try again.'
        : 'Could not start the run. Please try again.'
}

/** Turn a submit failure into a message and, where possible, a next step the user can act on. */
export function describeTaskSubmitError(error: unknown, step: TaskSubmitStep): TaskSubmitErrorInfo {
    if (!(error instanceof ApiError)) {
        return { message: error instanceof Error && error.message ? error.message : fallbackMessage(step) }
    }

    const code = error.code
    const message = backendMessage(error) ?? fallbackMessage(step)

    if (code && BILLING_LIMIT_CODES.has(code)) {
        return {
            message,
            button: {
                label: 'Manage billing',
                action: () => router.actions.push(urls.organizationBilling()),
            },
        }
    }

    if (code === CODE_ACCESS_REQUIRED_CODE) {
        return {
            message,
            button: {
                label: 'Learn more',
                action: () => window.open('https://posthog.com/desktop', '_blank'),
            },
        }
    }

    return { message }
}
