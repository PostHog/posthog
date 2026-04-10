import type { z } from 'zod'

import { withUiApp } from '@/resources/ui-apps'
import { DebugMcpUiAppsSchema } from '@/schema/tool-inputs'
import type { Context, ToolBase } from '@/tools/types'

const schema = DebugMcpUiAppsSchema

type Params = z.infer<typeof schema>

type Result = {
    message: string
    timestamp: string
    sdkInfo: { name: string; description: string }
    sampleData: { numbers: number[]; nested: { key: string; array: string[] } }
}

export const debugMcpUiAppsHandler: ToolBase<typeof schema, Result>['handler'] = async (
    _context: Context,
    params: Params
) => {
    return {
        message: params.message || 'Hello from debug-mcp-ui-apps!',
        timestamp: new Date().toISOString(),
        sdkInfo: {
            name: '@modelcontextprotocol/ext-apps',
            description: 'MCP Apps SDK for building interactive UI visualizations',
        },
        sampleData: {
            numbers: [1, 2, 3, 4, 5],
            nested: {
                key: 'value',
                array: ['a', 'b', 'c'],
            },
        },
    }
}

export default (): ToolBase<typeof schema, Result> =>
    withUiApp('debug', {
        name: 'debug-mcp-ui-apps',
        schema,
        handler: debugMcpUiAppsHandler,
    })
