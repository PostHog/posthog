import type { z } from 'zod'

import { DEBUG_RESOURCE_URI } from '@/resources/ui-apps-constants'
import { DebugMcpUiAppsSchema } from '@/schema/tool-inputs'
import type { Context, ToolBase } from '@/tools/types'

const schema = DebugMcpUiAppsSchema

type Params = z.infer<typeof schema>

export const debugMcpUiAppsHandler: ToolBase<typeof schema>['handler'] = async (_context: Context, params: Params) => {
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

const tool = (): ToolBase<typeof schema> => ({
    name: 'debug-mcp-ui-apps',
    schema,
    handler: debugMcpUiAppsHandler,
    _meta: {
        ui: {
            resourceUri: DEBUG_RESOURCE_URI,
        },
    },
})

export default tool
