import type { z } from 'zod'

import { ExecuteSQLSchema } from '@/schema/tool-inputs'
import type { Context, ToolBase } from '@/tools/types'

import { invokeMcpTool } from './invokeTool'

const schema = ExecuteSQLSchema

type Params = z.infer<typeof schema>

export const executeSqlHandler: ToolBase<typeof schema>['handler'] = async (context: Context, params: Params) => {
    const result = await invokeMcpTool(context, 'execute_sql', {
        query: params.query,
    })

    if (!result.success) {
        throw new Error(result.content)
    }

    return result.content
}

const tool = (): ToolBase<typeof schema> => ({
    name: 'execute-sql',
    schema,
    handler: executeSqlHandler,
})

export default tool
