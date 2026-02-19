import type { z } from 'zod'

import { DEMO_RESOURCE_URI } from '@/resources/ui-apps-constants'
import { DemoMcpUiAppsSchema } from '@/schema/tool-inputs'
import type { Context, ToolBase } from '@/tools/types'

const schema = DemoMcpUiAppsSchema

type Params = z.infer<typeof schema>

export const demoMcpUiAppsHandler: ToolBase<typeof schema>['handler'] = async (_context: Context, params: Params) => {
    return {
        message: params.message || 'Hello from demo-mcp-ui-apps!',
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
    name: 'demo-mcp-ui-apps',
    schema,
    handler: demoMcpUiAppsHandler,
    _meta: {
        ui: {
            resourceUri: DEMO_RESOURCE_URI,
        },
    },
})

export default tool
