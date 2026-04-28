// AUTO-GENERATED from services/mcp/definitions/sdk_doctor.yaml + OpenAPI — do not edit
import { z } from 'zod'

import type { Schemas } from '@/api/generated'
import { SdkDoctorReportRetrieveQueryParams } from '@/generated/sdk_doctor/api'
import type { Context, ToolBase, ZodObjectAny } from '@/tools/types'

const SdkDoctorGetSchema = SdkDoctorReportRetrieveQueryParams.extend({
    force_refresh: SdkDoctorReportRetrieveQueryParams.shape['force_refresh'].describe(
        'Set to true to bypass the Redis cache and re-query ClickHouse for SDK usage. Use sparingly — data is refreshed every 12 hours by a background job, so the cached answer is usually fine.'
    ),
})

const sdkDoctorGet = (): ToolBase<typeof SdkDoctorGetSchema, Schemas.SdkHealthReport> => ({
    name: 'sdk-doctor-get',
    schema: SdkDoctorGetSchema,
    handler: async (context: Context, params: z.infer<typeof SdkDoctorGetSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.SdkHealthReport>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/sdk_doctor/report/`,
            query: {
                force_refresh: params.force_refresh,
            },
        })
        return result
    },
})

export const GENERATED_TOOLS: Record<string, () => ToolBase<ZodObjectAny>> = {
    'sdk-doctor-get': sdkDoctorGet,
}
