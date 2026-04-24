import { HogQLSchemaInputSchema } from '@/schema/tool-inputs'
import type { Context, ToolBase } from '@/tools/types'

const schema = HogQLSchemaInputSchema

interface Field {
    name: string
    type: string
    nullable: boolean
    join_table?: string | null
    chain?: string[] | null
}

interface SchemaResult {
    tables: Array<{ name: string; fields: Field[] }>
    functions: string[]
}

export const hogqlSchemaHandler: ToolBase<typeof schema, SchemaResult>['handler'] = async (context: Context) => {
    const projectId = await context.stateManager.getProjectId()
    const result = await context.api.insights({ projectId }).schema()
    if (!result.success) {
        throw new Error(`Failed to fetch HogQL schema: ${result.error.message}`)
    }
    return result.data
}

const tool = (): ToolBase<typeof schema, SchemaResult> => ({
    name: 'hogql-schema',
    schema,
    handler: hogqlSchemaHandler,
})

export default tool
