import { ApiRequest } from 'lib/api'

import { HogFlow } from './hogflows/types'

// Scoped to this product to keep Jest's `--findRelatedTests` selection small —
// lib/api.ts and hogflows/types.ts are both imported by half the app.

export interface MessageAsset {
    invocation_id: string
    action_id: string
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

// Same-origin URL — used as an `<iframe src>` so the browser carries session auth.
export function getMessageAssetContentUrl(hogFlowId: HogFlow['id'], invocationId: string, actionId: string): string {
    return new ApiRequest()
        .hogFlow(hogFlowId)
        .withAction('assets/content')
        .withQueryString({ invocation_id: invocationId, action_id: actionId })
        .assembleFullUrl(true)
}
