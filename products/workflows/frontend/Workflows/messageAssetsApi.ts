import api, { ApiRequest } from 'lib/api'

import { HogFlow } from './hogflows/types'

// Asset endpoints + their types live here, not in lib/api.ts or hogflows/types.ts:
// both are imported by half the app, so editing either balloons the changed-files
// Jest selection (`--findRelatedTests`) to almost the whole suite. Keeping this
// workflows-scoped keeps that selection small.

// A rendered email snapshot captured when a workflow sent it. Mirrors
// MessageAssetSerializer in products/workflows/backend/api/message_assets.py.
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

// Same-origin URL for an asset's rendered HTML (the endpoint redirects to a presigned URL).
// Used directly as an <iframe src>; the browser carries session auth and follows the redirect.
export function getMessageAssetContentUrl(hogFlowId: HogFlow['id'], invocationId: string, actionId: string): string {
    return new ApiRequest()
        .hogFlow(hogFlowId)
        .withAction('assets/content')
        .withQueryString({ invocation_id: invocationId, action_id: actionId })
        .assembleFullUrl(true)
}

export async function getMessageAssetPdf(
    hogFlowId: HogFlow['id'],
    invocationId: string,
    actionId: string
): Promise<Blob> {
    const url = new ApiRequest()
        .hogFlow(hogFlowId)
        .withAction('assets/pdf')
        .withQueryString({ invocation_id: invocationId, action_id: actionId })
        .assembleFullUrl(true)
    const response = await api.getResponse(url)
    return await response.blob()
}
