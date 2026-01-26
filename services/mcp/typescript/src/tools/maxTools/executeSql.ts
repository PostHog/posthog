import type { z } from 'zod'

import { MaxExecuteSQLSchema } from '@/schema/tool-inputs'
import type { Context, ToolBase } from '@/tools/types'

import { invokeMaxTool } from './invokeMaxTool'

const schema = MaxExecuteSQLSchema

type Params = z.infer<typeof schema>

export const maxExecuteSqlHandler: ToolBase<typeof schema>['handler'] = async (context: Context, params: Params) => {
    const result = await invokeMaxTool(context, 'execute_sql', {
        query: params.query,
        viz_title: params.viz_title,
        viz_description: params.viz_description,
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
    name: 'max-execute-sql',
    schema,
    handler: maxExecuteSqlHandler,
})

export default tool
