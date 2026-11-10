import type { z } from 'zod'

import { ExplainSQLSchema } from '@/schema/tool-inputs'
import { POSTHOG_FORMATTED_RESULTS_OVERRIDE_KEY, type Context, type ToolBase } from '@/tools/types'

import { invokeMcpTool } from './invokeTool'

export const EXPLAIN_SQL_TOOL_NAME = 'explain-sql'

const schema = ExplainSQLSchema

type Params = z.infer<typeof schema>
type ExplainSqlResult = string | Record<string, unknown>

export const explainSqlHandler: ToolBase<typeof schema, ExplainSqlResult>['handler'] = async (
    context: Context,
    params: Params
): Promise<ExplainSqlResult> => {
    const result = await invokeMcpTool(context, 'explain_sql', {
        query: params.query,
        ...(params.connectionId !== undefined && { connectionId: params.connectionId }),
    })

    if (!result.success) {
        throw new Error(result.content)
    }

    return result.structured_content
        ? {
              ...result.structured_content,
              plan: result.content,
              [POSTHOG_FORMATTED_RESULTS_OVERRIDE_KEY]: result.content,
          }
        : result.content
}

const tool = (): ToolBase<typeof schema, ExplainSqlResult> => ({
    name: EXPLAIN_SQL_TOOL_NAME,
    schema,
    handler: explainSqlHandler,
})

export default tool
