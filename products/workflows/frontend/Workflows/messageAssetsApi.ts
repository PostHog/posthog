import api, { ApiRequest } from 'lib/api'

import { HogFlow, MessageAsset, MessageAssetsParams } from './hogflows/types'

// Asset endpoints live on the hog_flows viewset. Kept out of lib/api.ts on purpose:
// editing that high-fan-in file balloons the changed-files-based Jest selection
// (`--findRelatedTests`) to almost the whole suite. These are workflows-scoped, so
// they belong with the rest of the workflows frontend.

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
