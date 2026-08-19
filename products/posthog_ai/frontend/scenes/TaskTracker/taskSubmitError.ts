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
// `organization_deactivated` is deliberately not here — the billing page can't clear it, so it
// routes to support (below) to match the backend's "contact PostHog support" copy.
const BILLING_LIMIT_CODES = new Set(['posthog_code_billing_limit_exceeded', 'usage_limit_exceeded'])
const CODE_ACCESS_REQUIRED_CODE = 'code_access_required'
const ORGANIZATION_DEACTIVATED_CODE = 'organization_deactivated'

function stepPrefix(step: TaskSubmitStep): string {
    return step === 'create' ? 'Could not create the task' : 'Could not start the run'
}

// Only body-derived fields count as a real server reason. `ApiError.message` falls back to a
// synthetic "API request failed with status: X" (empty-body 5xx / gateway errors), which is not
// something to show a user, so we ignore it and let the step message take over.
function serverReason(error: ApiError): string | null {
    const fromData = typeof error.data?.error === 'string' ? error.data.error : null
    return fromData || error.detail || null
}

/** Turn a submit failure into a message and, where possible, a next step the user can act on. */
export function describeTaskSubmitError(error: unknown, step: TaskSubmitStep): TaskSubmitErrorInfo {
    if (!(error instanceof ApiError)) {
        return { message: `${stepPrefix(step)}. Please try again.` }
    }

    const reason = serverReason(error)

    if (error.code && BILLING_LIMIT_CODES.has(error.code)) {
        return {
            message: reason ?? `${stepPrefix(step)}. Please try again.`,
            button: { label: 'Manage billing', action: () => router.actions.push(urls.organizationBilling()) },
        }
    }

    if (error.code === CODE_ACCESS_REQUIRED_CODE) {
        return {
            message: reason ?? `${stepPrefix(step)}. Please try again.`,
            button: { label: 'Learn more', action: () => window.open('https://posthog.com/desktop', '_blank') },
        }
    }

    if (error.code === ORGANIZATION_DEACTIVATED_CODE) {
        return {
            message: reason ?? `${stepPrefix(step)}. Please try again.`,
            button: { label: 'Contact support', action: () => window.open('https://posthog.com/support', '_blank') },
        }
    }

    // Generic failure: always name the step, and add the server reason when there is a usable one.
    return { message: reason ? `${stepPrefix(step)}: ${reason}` : `${stepPrefix(step)}. Please try again.` }
}
