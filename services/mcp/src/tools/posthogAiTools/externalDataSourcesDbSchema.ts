import { z } from 'zod'

import { ExternalDataSourceTypeSchema } from '@/schema/tool-inputs'
import type { Context, ToolBase } from '@/tools/types'

const schema = z.object({
    source_type: ExternalDataSourceTypeSchema.describe(
        'Required. The source type name (e.g. "Postgres", "MySQL", "Stripe"). Use external-data-sources-wizard to list the valid source types and their required fields.'
    ),
    payload: z
        .record(z.string(), z.unknown())
        .default({})
        .describe(
            'Connection details for the source, passed as a flat set of keys. Either include `credential_id` (an id from data-warehouse-stored-credentials-list, for the same source_type) to use credentials a user already stored — the stored secrets are used server-side and are never returned, and the credential stays available for data-warehouse-source-setup — or pass the credential fields inline. Inline keys depend on source_type. For database sources: host, port, database, user, password, schema. For SaaS sources: api_key or OAuth fields. For source_type "Custom" (a user-defined REST API): `manifest_json` (a stringified RESTAPIConfig describing client.base_url, auth, and resources) plus `auth_token` (bearer), `auth_api_key` (api_key), or `auth_password` (http_basic). Use external-data-sources-wizard (pass source_type) to see required fields per source type. Do not pass unresolved {"secretRef": ...} objects. Example with a stored credential: {"credential_id": "<id>"}.'
        ),
})

type Params = z.input<typeof schema>

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
