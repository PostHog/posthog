// AUTO-GENERATED from services/mcp/definitions/data_management.yaml + OpenAPI — do not edit
import { z } from 'zod'

import type { Schemas } from '@/api/generated'
import * as orvalSchemas from '@/generated/data_management/api'
import type { Context, ToolBase, ZodObjectAny } from '@/tools/types'

const SchemaPropertyGroupCreateSchema = () => {
    const SchemaPropertyGroupsCreateBody = orvalSchemas.SchemaPropertyGroupsCreateBody()
    return SchemaPropertyGroupsCreateBody
}

const schemaPropertyGroupCreate = (): ToolBase<
    ReturnType<typeof SchemaPropertyGroupCreateSchema>,
    Schemas.SchemaPropertyGroup
> => ({
    name: 'schema-property-group-create',
    schema: SchemaPropertyGroupCreateSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof SchemaPropertyGroupCreateSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.name !== undefined) {
            body['name'] = params.name
        }
        if (params.description !== undefined) {
            body['description'] = params.description
        }
        if (params.properties !== undefined) {
            body['properties'] = params.properties
        }
        const result = await context.api.request<Schemas.SchemaPropertyGroup>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/schema_property_groups/`,
            body,
        })
        return result
    },
})

const EventSchemaCreateSchema = () => {
    const EventSchemasCreateBody = orvalSchemas.EventSchemasCreateBody()
    return EventSchemasCreateBody
}

const eventSchemaCreate = (): ToolBase<ReturnType<typeof EventSchemaCreateSchema>, Schemas.EventSchema> => ({
    name: 'event-schema-create',
    schema: EventSchemaCreateSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof EventSchemaCreateSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.event_definition !== undefined) {
            body['event_definition'] = params.event_definition
        }
        if (params.property_group_id !== undefined) {
            body['property_group_id'] = params.property_group_id
        }
        const result = await context.api.request<Schemas.EventSchema>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/event_schemas/`,
            body,
        })
        return result
    },
})

export const GENERATED_TOOLS: Record<string, () => ToolBase<ZodObjectAny>> = {
    'schema-property-group-create': schemaPropertyGroupCreate,
    'event-schema-create': eventSchemaCreate,
}
