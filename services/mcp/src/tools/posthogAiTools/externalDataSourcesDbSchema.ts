import { z } from 'zod'

import { ExternalDataSourceTypeSchema, ExternalDataSourcePayloadSchema } from '@/schema/tool-inputs'
import type { Context, ToolBase } from '@/tools/types'

const schema = z.object({
    source_type: ExternalDataSourceTypeSchema,
    payload: ExternalDataSourcePayloadSchema,
})

type Params = z.infer<typeof schema>

const tool = (): ToolBase<typeof schema, unknown> => ({
    name: 'external-data-sources-db-schema',
    schema,
    handler: async (context: Context, params: Params) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<unknown>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/external_data_sources/database_schema/`,
            body: {
                ...params.payload,
                source_type: params.source_type,
            },
        })
        return result
    },
})

export default tool
