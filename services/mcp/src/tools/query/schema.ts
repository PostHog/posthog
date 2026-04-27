import { HogQLSchemaInputSchema } from '@/schema/tool-inputs'
import type { Context, ToolBase } from '@/tools/types'

const schema = HogQLSchemaInputSchema

interface DatabaseSchemaField {
    name: string
    hogql_value: string
    type: string
    schema_valid: boolean
    chain?: Array<string | number> | null
    fields?: string[] | null
    table?: string | null
    id?: string | null
}

interface DatabaseSchemaTable {
    name: string
    type: string
    id?: string
    fields: Record<string, DatabaseSchemaField>
}

interface DataWarehouseViewLink {
    id: string
    source_table_name?: string | null
    source_table_key?: string | null
    joining_table_name?: string | null
    joining_table_key?: string | null
    field_name?: string | null
    created_at?: string | null
}

interface SchemaResult {
    tables: Record<string, DatabaseSchemaTable>
    joins: DataWarehouseViewLink[]
}

export const hogqlSchemaHandler: ToolBase<typeof schema, SchemaResult>['handler'] = async (context: Context) => {
    const projectId = await context.stateManager.getProjectId()
    const result = await context.api.insights({ projectId }).query({
        query: { kind: 'DatabaseSchemaQuery' },
    })
    if (!result.success) {
        throw new Error(`Failed to fetch HogQL schema: ${result.error.message}`)
    }
    return result.data as unknown as SchemaResult
}

const tool = (): ToolBase<typeof schema, SchemaResult> => ({
    name: 'hogql-schema',
    schema,
    handler: hogqlSchemaHandler,
})

export default tool
