import type { App } from '@modelcontextprotocol/ext-apps'

import type { UiAppKey } from '../../resources/ui-apps.generated'
import { APP_DATA_META_KEY } from '../types'

interface RenderUiDataResult {
    structuredContent?: unknown
    isError?: boolean
}

export async function loadRenderUiData(
    app: Pick<App, 'callServerTool'>,
    toolName: string,
    input: Record<string, unknown>,
    appKey: UiAppKey
): Promise<RenderUiDataResult> {
    const useExec = appKey === 'query-results'
    const result = await app.callServerTool(
        useExec
            ? { name: 'exec', arguments: { command: `call --json ${toolName} ${JSON.stringify(input)}` } }
            : { name: toolName, arguments: input }
    )
    if (!useExec || result.isError) {
        return result
    }
    const data = result.structuredContent ?? result._meta?.[APP_DATA_META_KEY]
    if (data !== undefined) {
        return { structuredContent: data }
    }
    const text = result.content.find((item) => item.type === 'text')?.text
    return { structuredContent: text === undefined ? undefined : JSON.parse(text) }
}
