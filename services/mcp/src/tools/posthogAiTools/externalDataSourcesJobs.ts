import { z } from 'zod'

import {
    ExternalDataJobsAfterSchema,
    ExternalDataJobsBeforeSchema,
    ExternalDataJobsSchemasSchema,
} from '@/schema/tool-inputs'
import type { Context, ToolBase } from '@/tools/types'

const schema = z.object({
    id: z.string().describe('A UUID string identifying this external data source.'),
    after: ExternalDataJobsAfterSchema.optional(),
    before: ExternalDataJobsBeforeSchema.optional(),
    schemas: ExternalDataJobsSchemasSchema.optional(),
})

type Params = z.infer<typeof schema>

const tool = (): ToolBase<typeof schema, unknown> => ({
    name: 'external-data-sources-jobs',
    schema,
    handler: async (context: Context, params: Params) => {
        const projectId = await context.stateManager.getProjectId()
        const query: Record<string, string | string[]> = {}
        if (params.after) {
            query.after = params.after
        }
        if (params.before) {
            query.before = params.before
        }
        if (params.schemas) {
            query.schemas = params.schemas
        }
        const result = await context.api.request<unknown>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/external_data_sources/${encodeURIComponent(String(params.id))}/jobs/`,
            query,
        })
        return result
    },
})

export default tool
