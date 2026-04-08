// AUTO-GENERATED from products/replay/mcp/tools.yaml + OpenAPI — do not edit
import { z } from 'zod'

import type { Schemas } from '@/api/generated'
import { SessionRecordingsListQueryParams, SessionRecordingsRetrieveParams } from '@/generated/replay/api'
import { withPostHogUrl, pickResponseFields, type WithPostHogUrl } from '@/tools/tool-utils'
import type { Context, ToolBase, ZodObjectAny } from '@/tools/types'

const SessionRecordingsListSchema = SessionRecordingsListQueryParams

const sessionRecordingsList = (): ToolBase<
    typeof SessionRecordingsListSchema,
    WithPostHogUrl<Schemas.SessionRecordingListResponse>
> => ({
    name: 'session-recordings-list',
    schema: SessionRecordingsListSchema,
    handler: async (context: Context, params: z.infer<typeof SessionRecordingsListSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.SessionRecordingListResponse>({
            method: 'GET',
            path: `/api/projects/${projectId}/session_recordings/`,
            query: {
                actions: params.actions,
                console_log_filters: params.console_log_filters,
                date_from: params.date_from,
                date_to: params.date_to,
                distinct_ids: params.distinct_ids,
                events: params.events,
                filter_test_accounts: params.filter_test_accounts,
                limit: params.limit,
                offset: params.offset,
                operand: params.operand,
                order: params.order,
                order_direction: params.order_direction,
                person_uuid: params.person_uuid,
                properties: params.properties,
                session_ids: params.session_ids,
            },
        })
        const filtered = {
            ...result,
            results: result.results.map((item: any) =>
                pickResponseFields(item, [
                    'id',
                    'distinct_id',
                    'viewed',
                    'recording_duration',
                    'active_seconds',
                    'inactive_seconds',
                    'start_time',
                    'end_time',
                    'click_count',
                    'keypress_count',
                    'console_error_count',
                    'start_url',
                    'person',
                    'activity_score',
                    'snapshot_source',
                ])
            ),
        } as typeof result
        return await withPostHogUrl(
            context,
            {
                ...filtered,
                results: await Promise.all(
                    filtered.results.map((item) => withPostHogUrl(context, item, `/replay/${item.id}`))
                ),
            },
            '/replay'
        )
    },
})

const SessionRecordingsRetrieveSchema = SessionRecordingsRetrieveParams.omit({ project_id: true })

const sessionRecordingsRetrieve = (): ToolBase<
    typeof SessionRecordingsRetrieveSchema,
    WithPostHogUrl<Schemas.SessionRecording>
> => ({
    name: 'session-recordings-retrieve',
    schema: SessionRecordingsRetrieveSchema,
    handler: async (context: Context, params: z.infer<typeof SessionRecordingsRetrieveSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.SessionRecording>({
            method: 'GET',
            path: `/api/projects/${projectId}/session_recordings/${params.id}/`,
        })
        return await withPostHogUrl(context, result, `/replay/${result.id}`)
    },
})

export const GENERATED_TOOLS: Record<string, () => ToolBase<ZodObjectAny>> = {
    'session-recordings-list': sessionRecordingsList,
    'session-recordings-retrieve': sessionRecordingsRetrieve,
}
