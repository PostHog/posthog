import type { z } from 'zod'

import { QueryValidateInputSchema } from '@/schema/tool-inputs'
import type { Context, ToolBase } from '@/tools/types'

const schema = QueryValidateInputSchema

type Params = z.infer<typeof schema>

interface Notice {
    message: string
    start?: number | null
    end?: number | null
    fix?: string | null
}

interface ValidateResult {
    isValid: boolean
    query: string
    errors: Notice[]
    warnings: Notice[]
    notices: Notice[]
    table_names: string[]
    ch_table_names?: string[] | null
}

export const queryValidateHandler: ToolBase<typeof schema, ValidateResult>['handler'] = async (
    context: Context,
    params: Params
) => {
    const { query, language, connectionId } = params

    const projectId = await context.stateManager.getProjectId()

    const result = await context.api.insights({ projectId }).validate({ query, language, connectionId })

    if (!result.success) {
        throw new Error(`Failed to validate query: ${result.error.message}`)
    }

    const data = result.data
    return {
        isValid: data.isValid,
        query: data.query ?? query,
        errors: data.errors ?? [],
        warnings: data.warnings ?? [],
        notices: data.notices ?? [],
        table_names: data.table_names ?? [],
        ch_table_names: data.ch_table_names ?? null,
    }
}

const tool = (): ToolBase<typeof schema, ValidateResult> => ({
    name: 'query-validate',
    schema,
    handler: queryValidateHandler,
})

export default tool
