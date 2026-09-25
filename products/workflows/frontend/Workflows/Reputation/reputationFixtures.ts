import type { WorkflowEmailSendingRatesApi } from 'products/workflows/frontend/generated/api.schemas'

/** A workflow row of the reputation response. A pause reason marks the workflow as paused. */
export function workflowRates(
    id: string,
    name: string,
    rates: Pick<WorkflowEmailSendingRatesApi, 'emails_sent' | 'bounce_rate' | 'complaint_rate'>,
    pausedReason?: string
): WorkflowEmailSendingRatesApi {
    return {
        hog_flow_id: id,
        hog_flow_name: name,
        ...rates,
        email_sending_paused: pausedReason !== undefined,
        email_sending_paused_at: pausedReason !== undefined ? '2026-09-01T00:00:00Z' : null,
        email_sending_paused_reason: pausedReason ?? '',
    }
}
