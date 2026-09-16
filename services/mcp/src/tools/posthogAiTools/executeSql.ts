import type { z } from 'zod'

import { ExecuteSQLSchema } from '@/schema/tool-inputs'
import { POSTHOG_FORMATTED_RESULTS_OVERRIDE_KEY, type Context, type ToolBase } from '@/tools/types'

import { invokeMcpTool } from './invokeTool'

export const EXECUTE_SQL_TOOL_NAME = 'execute-sql'

const schema = ExecuteSQLSchema

type Params = z.infer<typeof schema>
type ExecuteSqlResult = string | Record<string, unknown>

export const executeSqlHandler: ToolBase<typeof schema, ExecuteSqlResult>['handler'] = async (
    context: Context,
    params: Params
): Promise<ExecuteSqlResult> => {
    const result = await invokeMcpTool(context, 'execute_sql', {
        query: params.query,
        truncate: params.truncate ?? true,
        ...(params.connectionId !== undefined && { connectionId: params.connectionId }),
        ...(params.sendRawQuery !== undefined && { sendRawQuery: params.sendRawQuery }),
    })

    if (!result.success) {
        throw new Error(result.content)
    }

    return result.structured_content
        ? {
              ...result.structured_content,
              results: result.content,
              [POSTHOG_FORMATTED_RESULTS_OVERRIDE_KEY]: result.content,
          }
        : result.content
}

const tool = (): ToolBase<typeof schema, ExecuteSqlResult> => ({
    name: EXECUTE_SQL_TOOL_NAME,
    schema,
    handler: executeSqlHandler,
})

export default tool
