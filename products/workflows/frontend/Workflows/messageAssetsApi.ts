import api, { ApiRequest } from 'lib/api'

import { TeamType } from '~/types'

import { HogFlow } from './hogflows/types'

// Scoped to this product to keep Jest's `--findRelatedTests` selection small —
// lib/api.ts and hogflows/types.ts are both imported by half the app.

export interface MessageAsset {
    invocation_id: string
    action_id: string
    /** Workflow id that sent this email — used by the person Emails tab to navigate back. */
    function_id: string
    /** Workflow name; empty when the workflow has been deleted (fall back to function_id). */
    function_name: string
    /** HogFlowBatchJob id for batch-triggered sends; empty for event-triggered runs. */
    parent_run_id: string
    kind: string
    distinct_id: string
    person_id: string
    recipient: string
    subject: string
    status: string
    sent_at: string
}

export interface MessageAssetsParams {
    parent_run_id?: string
    action_id?: string
    /** Pre-filter to a single invocation — used to deep-link from a log entry to the email that run sent. */
    invocation_id?: string
    distinct_id?: string
    search?: string
    after?: string
    before?: string
    limit?: number
    offset?: number
}

export async function getMessageAssets(
    hogFlowId: HogFlow['id'],
    params: MessageAssetsParams = {}
): Promise<MessageAsset[]> {
    return await new ApiRequest().hogFlow(hogFlowId).withAction('assets').withQueryString(params).get()
}

export interface PersonMessageAssetsParams {
    after?: string
    before?: string
    limit?: number
    offset?: number
}

export async function getPersonMessageAssets(
    teamId: TeamType['id'],
    personId: string,
    params: PersonMessageAssetsParams = {}
): Promise<MessageAsset[]> {
    const qs = new URLSearchParams(
        Object.entries(params).reduce<Record<string, string>>((acc, [k, v]) => {
            if (v !== undefined && v !== null) {
                acc[k] = String(v)
            }
            return acc
        }, {})
    ).toString()
    const suffix = qs ? `?${qs}` : ''
    return await api.get(`api/projects/${teamId}/persons/${encodeURIComponent(personId)}/emails/${suffix}`)
}

// Same-origin URL — used as an `<iframe src>` so the browser carries session auth.
export function getMessageAssetContentUrl(hogFlowId: HogFlow['id'], invocationId: string, actionId: string): string {
    return new ApiRequest()
        .hogFlow(hogFlowId)
        .withAction('assets/content')
        .withQueryString({ invocation_id: invocationId, action_id: actionId })
        .assembleFullUrl(true)
}
