import { z } from 'zod'

import { ExternalDataSourcePayloadSchema, ExternalDataSourceTypeSchema } from '@/schema/tool-inputs'
import type { Context, ToolBase } from '@/tools/types'

// Mirrors PREVIEW_MAX_ROWS / PREVIEW_DEFAULT_ROWS in posthog/temporal/data_imports/sources/custom/source.py.
// The backend serializer enforces both regardless; naming them here keeps the two sides greppable together.
const PREVIEW_MAX_ROWS = 50
const PREVIEW_DEFAULT_ROWS = 10

const schema = z.object({
    source_type: ExternalDataSourceTypeSchema,
    payload: ExternalDataSourcePayloadSchema,
    resource_name: z
        .string()
        .describe(
            'Which manifest resource (table) to read a sample from — one of the resource names in manifest_json.'
        ),
    limit: z
        .number()
        .int()
        .min(1)
        .max(PREVIEW_MAX_ROWS)
        .optional()
        .describe(`Maximum sample rows to return (1–${PREVIEW_MAX_ROWS}). Defaults to ${PREVIEW_DEFAULT_ROWS}.`),
})

type Params = z.infer<typeof schema>

const tool = (): ToolBase<typeof schema, unknown> => ({
    name: 'external-data-sources-preview-resource',
    schema,
    handler: async (context: Context, params: Params) => {
        const projectId = await context.stateManager.getProjectId()
        // The preview endpoint nests credentials under `payload` (unlike db-schema's flat body),
        // so forward the payload object untouched rather than spreading it.
        const result = await context.api.request<unknown>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/external_data_sources/preview_resource/`,
            body: {
                source_type: params.source_type,
                payload: params.payload,
                resource_name: params.resource_name,
                limit: params.limit,
            },
        })
        return result
    },
})

export default tool
