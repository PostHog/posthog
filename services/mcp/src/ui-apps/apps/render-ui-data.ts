import type { App } from '@modelcontextprotocol/ext-apps'
import type { CallToolResult } from '@modelcontextprotocol/sdk/types.js'

import type { UiAppKey } from '../../resources/ui-apps.generated'
import { APP_DATA_META_KEY } from '../types'

interface RenderUiDataResult {
    structuredContent?: unknown
    isError?: boolean
}

export interface RenderUiDataRequest {
    name: string
    arguments: Record<string, unknown>
}

/** The `tools/call` that fetches a visualization's data; the server preloads with the same call. */
export function renderUiDataRequest(
    toolName: string,
    input: Record<string, unknown>,
    appKey: UiAppKey
): RenderUiDataRequest {
    return appKey === 'query-results' ? execDataRequest(toolName, input) : { name: toolName, arguments: input }
}

function execDataRequest(toolName: string, input: Record<string, unknown>): RenderUiDataRequest {
    return { name: 'exec', arguments: { command: `call --json ${toolName} ${JSON.stringify(input)}` } }
}

export function readRenderUiData(result: CallToolResult, appKey: UiAppKey): RenderUiDataResult {
    return appKey === 'query-results' ? readExecData(result) : result
}

function readExecData(result: CallToolResult): RenderUiDataResult {
    if (result.isError) {
        return result
    }
    const data = result.structuredContent ?? result._meta?.[APP_DATA_META_KEY]
    if (data !== undefined) {
        return { structuredContent: data }
    }
    const text = result.content.find((item) => item.type === 'text')?.text
    return { structuredContent: text === undefined ? undefined : JSON.parse(text) }
}

export async function loadRenderUiData(
    app: Pick<App, 'callServerTool'>,
    toolName: string,
    input: Record<string, unknown>,
    appKey: UiAppKey,
    resultMeta?: Record<string, unknown> | null,
    envelopeAppData?: unknown
): Promise<RenderUiDataResult> {
    const preloaded = resultMeta?.[APP_DATA_META_KEY] ?? envelopeAppData
    if (preloaded !== undefined && preloaded !== null) {
        return { structuredContent: preloaded }
    }
    const request = renderUiDataRequest(toolName, input, appKey)
    try {
        return readRenderUiData(await app.callServerTool(request), appKey)
    } catch (error) {
        if (request.name === 'exec') {
            throw error
        }
        // Some hosts refuse an app call to a tool that `tools/list` did not advertise, so retry through `exec`.
        try {
            return readExecData(await app.callServerTool(execDataRequest(toolName, input)))
        } catch {
            throw error
        }
    }
}
