import type { z } from 'zod'

import { MaxExecuteSQLSchema } from '@/schema/tool-inputs'
import type { Context, ToolBase } from '@/tools/types'

import { invokeMaxTool } from './invokeMaxTool'

const schema = MaxExecuteSQLSchema

type Params = z.infer<typeof schema>

export const executeSqlHandler: ToolBase<typeof schema>['handler'] = async (context: Context, params: Params) => {
    const result = await invokeMaxTool(context, 'execute_sql', {
        query: params.query,
    })

    if (!result.success) {
        throw new Error(result.content)
    }

    return {
        content: result.content,
        data: result.data,
    }
}

const tool = (): ToolBase<typeof schema> => ({
    name: 'execute-sql',
    schema,
    handler: executeSqlHandler,
})

export default tool
