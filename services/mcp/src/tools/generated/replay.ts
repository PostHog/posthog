// AUTO-GENERATED from products/replay/mcp/tools.yaml + OpenAPI — do not edit
import { z } from 'zod'

import type { Schemas } from '@/api/generated'
import {
    SessionRecordingPlaylistsCreateBody,
    SessionRecordingPlaylistsListQueryParams,
    SessionRecordingPlaylistsPartialUpdateBody,
    SessionRecordingPlaylistsPartialUpdateParams,
    SessionRecordingPlaylistsRetrieveParams,
    SessionRecordingsDestroyParams,
    SessionRecordingsRetrieveParams,
} from '@/generated/replay/api'
import { withUiApp } from '@/resources/ui-apps'
import { createQueryWrapper } from '@/tools/query-wrapper-factory'
import { withPostHogUrl, type WithPostHogUrl } from '@/tools/tool-utils'
import type { Context, ToolBase, ZodObjectAny } from '@/tools/types'

const SessionRecordingGetSchema = SessionRecordingsRetrieveParams.omit({ project_id: true })

const sessionRecordingGet = (): ToolBase<typeof SessionRecordingGetSchema, WithPostHogUrl<Schemas.SessionRecording>> =>
    withUiApp('session-recording', {
        name: 'session-recording-get',
        schema: SessionRecordingGetSchema,
        handler: async (context: Context, params: z.infer<typeof SessionRecordingGetSchema>) => {
            const projectId = await context.stateManager.getProjectId()
            const result = await context.api.request<Schemas.SessionRecording>({
                method: 'GET',
                path: `/api/projects/${encodeURIComponent(String(projectId))}/session_recordings/${encodeURIComponent(String(params.id))}/`,
            })
            return await withPostHogUrl(context, result, `/replay/${result.id}`)
        },
    })

const SessionRecordingDeleteSchema = SessionRecordingsDestroyParams.omit({ project_id: true })

const sessionRecordingDelete = (): ToolBase<typeof SessionRecordingDeleteSchema, unknown> => ({
    name: 'session-recording-delete',
    schema: SessionRecordingDeleteSchema,
    handler: async (context: Context, params: z.infer<typeof SessionRecordingDeleteSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<unknown>({
            method: 'DELETE',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/session_recordings/${encodeURIComponent(String(params.id))}/`,
        })
        return result
    },
})

const SessionRecordingPlaylistsListSchema = SessionRecordingPlaylistsListQueryParams

const sessionRecordingPlaylistsList = (): ToolBase<
    typeof SessionRecordingPlaylistsListSchema,
    WithPostHogUrl<Schemas.PaginatedSessionRecordingPlaylistList>
> => ({
    name: 'session-recording-playlists-list',
    schema: SessionRecordingPlaylistsListSchema,
    handler: async (context: Context, params: z.infer<typeof SessionRecordingPlaylistsListSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.PaginatedSessionRecordingPlaylistList>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/session_recording_playlists/`,
            query: {
                created_by: params.created_by,
                limit: params.limit,
                offset: params.offset,
                short_id: params.short_id,
            },
        })
        return await withPostHogUrl(context, result, '/replay')
    },
})

const SessionRecordingPlaylistGetSchema = SessionRecordingPlaylistsRetrieveParams.omit({ project_id: true })

const sessionRecordingPlaylistGet = (): ToolBase<
    typeof SessionRecordingPlaylistGetSchema,
    Schemas.SessionRecordingPlaylist
> => ({
    name: 'session-recording-playlist-get',
    schema: SessionRecordingPlaylistGetSchema,
    handler: async (context: Context, params: z.infer<typeof SessionRecordingPlaylistGetSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.SessionRecordingPlaylist>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/session_recording_playlists/${encodeURIComponent(String(params.short_id))}/`,
        })
        return result
    },
})

const SessionRecordingPlaylistCreateSchema = SessionRecordingPlaylistsCreateBody

const sessionRecordingPlaylistCreate = (): ToolBase<
    typeof SessionRecordingPlaylistCreateSchema,
    Schemas.SessionRecordingPlaylist
> => ({
    name: 'session-recording-playlist-create',
    schema: SessionRecordingPlaylistCreateSchema,
    handler: async (context: Context, params: z.infer<typeof SessionRecordingPlaylistCreateSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.name !== undefined) {
            body['name'] = params.name
        }
        if (params.derived_name !== undefined) {
            body['derived_name'] = params.derived_name
        }
        if (params.description !== undefined) {
            body['description'] = params.description
        }
        if (params.pinned !== undefined) {
            body['pinned'] = params.pinned
        }
        if (params.deleted !== undefined) {
            body['deleted'] = params.deleted
        }
        if (params.filters !== undefined) {
            body['filters'] = params.filters
        }
        if (params.type !== undefined) {
            body['type'] = params.type
        }
        const result = await context.api.request<Schemas.SessionRecordingPlaylist>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/session_recording_playlists/`,
            body,
        })
        return result
    },
})

const SessionRecordingPlaylistUpdateSchema = SessionRecordingPlaylistsPartialUpdateParams.omit({
    project_id: true,
}).extend(SessionRecordingPlaylistsPartialUpdateBody.shape)

const sessionRecordingPlaylistUpdate = (): ToolBase<
    typeof SessionRecordingPlaylistUpdateSchema,
    Schemas.SessionRecordingPlaylist
> => ({
    name: 'session-recording-playlist-update',
    schema: SessionRecordingPlaylistUpdateSchema,
    handler: async (context: Context, params: z.infer<typeof SessionRecordingPlaylistUpdateSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.name !== undefined) {
            body['name'] = params.name
        }
        if (params.derived_name !== undefined) {
            body['derived_name'] = params.derived_name
        }
        if (params.description !== undefined) {
            body['description'] = params.description
        }
        if (params.pinned !== undefined) {
            body['pinned'] = params.pinned
        }
        if (params.deleted !== undefined) {
            body['deleted'] = params.deleted
        }
        if (params.filters !== undefined) {
            body['filters'] = params.filters
        }
        const result = await context.api.request<Schemas.SessionRecordingPlaylist>({
            method: 'PATCH',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/session_recording_playlists/${encodeURIComponent(String(params.short_id))}/`,
            body,
        })
        return result
    },
})

// --- Query wrapper schemas from schema.json ---

const integer = z.coerce.number().int()

const RecordingOrder = z.enum([
    'duration',
    'recording_duration',
    'inactive_seconds',
    'active_seconds',
    'start_time',
    'console_error_count',
    'click_count',
    'keypress_count',
    'mouse_activity_count',
    'activity_score',
    'recording_ttl',
])

const RecordingOrderDirection = z.enum(['ASC', 'DESC'])

const AssistantStringOrBooleanValuePropertyFilterOperator = z.enum([
    'exact',
    'is_not',
    'icontains',
    'not_icontains',
    'regex',
    'not_regex',
])

const AssistantGenericPropertyFilterType = z.enum(['event', 'person', 'session', 'feature'])

const AssistantNumericValuePropertyFilterOperator = z.enum(['exact', 'gt', 'lt'])

const AssistantArrayPropertyFilterOperator = z.enum(['exact', 'is_not'])

const AssistantDateTimePropertyFilterOperator = z.enum(['is_date_exact', 'is_date_before', 'is_date_after'])

const AssistantSetPropertyFilterOperator = z.enum(['is_set', 'is_not_set'])

const AssistantGenericPropertyFilter = z.union([
    z.object({
        key: z.string().describe('Use one of the properties the user has provided in the plan.'),
        operator: AssistantStringOrBooleanValuePropertyFilterOperator.describe(
            '`icontains` - case insensitive contains. `not_icontains` - case insensitive does not contain. `regex` - matches the regex pattern. `not_regex` - does not match the regex pattern.'
        ),
        type: AssistantGenericPropertyFilterType,
        value: z
            .string()
            .describe(
                'Only use property values from the plan. If the operator is `regex` or `not_regex`, the value must be a valid ClickHouse regex pattern to match against. Otherwise, the value must be a substring that will be matched against the property value. Use the string values `true` or `false` for boolean properties.'
            ),
    }),
    z.object({
        key: z.string().describe('Use one of the properties the user has provided in the plan.'),
        operator: AssistantNumericValuePropertyFilterOperator,
        type: AssistantGenericPropertyFilterType,
        value: z.coerce.number(),
    }),
    z.object({
        key: z.string().describe('Use one of the properties the user has provided in the plan.'),
        operator: AssistantArrayPropertyFilterOperator.describe(
            '`exact` - exact match of any of the values. `is_not` - does not match any of the values.'
        ),
        type: AssistantGenericPropertyFilterType,
        value: z
            .array(z.string())
            .describe(
                'Only use property values from the plan. Always use strings as values. If you have a number, convert it to a string first. If you have a boolean, convert it to a string "true" or "false".'
            ),
    }),
    z.object({
        key: z.string().describe('Use one of the properties the user has provided in the plan.'),
        operator: AssistantDateTimePropertyFilterOperator,
        type: AssistantGenericPropertyFilterType,
        value: z.string().describe('Value must be a date in ISO 8601 format.'),
    }),
    z.object({
        key: z.string().describe('Use one of the properties the user has provided in the plan.'),
        operator: AssistantSetPropertyFilterOperator.describe(
            "`is_set` - the property has any value. `is_not_set` - the property doesn't have a value or wasn't collected."
        ),
        type: AssistantGenericPropertyFilterType,
    }),
])

const AssistantGroupPropertyFilter = z.union([
    z.object({
        group_type_index: integer.describe('Index of the group type from the group mapping.'),
        key: z.string().describe('Use one of the properties the user has provided in the plan.'),
        operator: AssistantStringOrBooleanValuePropertyFilterOperator.describe(
            '`icontains` - case insensitive contains. `not_icontains` - case insensitive does not contain. `regex` - matches the regex pattern. `not_regex` - does not match the regex pattern.'
        ),
        type: z.literal('group').default('group'),
        value: z
            .string()
            .describe(
                'Only use property values from the plan. If the operator is `regex` or `not_regex`, the value must be a valid ClickHouse regex pattern to match against. Otherwise, the value must be a substring that will be matched against the property value. Use the string values `true` or `false` for boolean properties.'
            ),
    }),
    z.object({
        group_type_index: integer.describe('Index of the group type from the group mapping.'),
        key: z.string().describe('Use one of the properties the user has provided in the plan.'),
        operator: AssistantNumericValuePropertyFilterOperator,
        type: z.literal('group').default('group'),
        value: z.coerce.number(),
    }),
    z.object({
        group_type_index: integer.describe('Index of the group type from the group mapping.'),
        key: z.string().describe('Use one of the properties the user has provided in the plan.'),
        operator: AssistantArrayPropertyFilterOperator.describe(
            '`exact` - exact match of any of the values. `is_not` - does not match any of the values.'
        ),
        type: z.literal('group').default('group'),
        value: z
            .array(z.string())
            .describe(
                'Only use property values from the plan. Always use strings as values. If you have a number, convert it to a string first. If you have a boolean, convert it to a string "true" or "false".'
            ),
    }),
    z.object({
        group_type_index: integer.describe('Index of the group type from the group mapping.'),
        key: z.string().describe('Use one of the properties the user has provided in the plan.'),
        operator: AssistantDateTimePropertyFilterOperator,
        type: z.literal('group').default('group'),
        value: z.string().describe('Value must be a date in ISO 8601 format.'),
    }),
    z.object({
        group_type_index: integer.describe('Index of the group type from the group mapping.'),
        key: z.string().describe('Use one of the properties the user has provided in the plan.'),
        operator: AssistantSetPropertyFilterOperator.describe(
            "`is_set` - the property has any value. `is_not_set` - the property doesn't have a value or wasn't collected."
        ),
        type: z.literal('group').default('group'),
    }),
])

const AssistantCohortPropertyFilter = z.object({
    key: z.literal('id').default('id'),
    operator: z.literal('in').default('in'),
    type: z
        .literal('cohort')
        .describe(
            'Filter events by cohort membership. Use this to narrow down results to persons belonging to a specific cohort. Example: `{ type: "cohort", key: "id", value: 42, operator: "in" }`'
        )
        .default('cohort'),
    value: integer.describe('The cohort ID to filter by.'),
})

const AssistantElementPropertyFilter = z.union([
    z.object({
        key: z
            .enum(['tag_name', 'text', 'href', 'selector'])
            .describe(
                'The element property to filter on. `tag_name` — HTML tag (e.g., `button`, `a`, `input`). `text` — visible text content of the element. `href` — the `href` attribute for links. `selector` — a CSS selector matching the element (e.g., `div.main > button.cta`).'
            ),
        operator: AssistantStringOrBooleanValuePropertyFilterOperator.describe(
            '`icontains` - case insensitive contains. `not_icontains` - case insensitive does not contain. `regex` - matches the regex pattern. `not_regex` - does not match the regex pattern.'
        ),
        type: z
            .literal('element')
            .describe(
                'Filter by autocaptured HTML element properties (`$autocapture`, `$rageclick`). Example: `{ type: "element", key: "text", value: "Sign Up", operator: "exact" }`'
            )
            .default('element'),
        value: z
            .string()
            .describe(
                'Only use property values from the plan. If the operator is `regex` or `not_regex`, the value must be a valid ClickHouse regex pattern to match against. Otherwise, the value must be a substring that will be matched against the property value. Use the string values `true` or `false` for boolean properties.'
            ),
    }),
    z.object({
        key: z
            .enum(['tag_name', 'text', 'href', 'selector'])
            .describe(
                'The element property to filter on. `tag_name` — HTML tag (e.g., `button`, `a`, `input`). `text` — visible text content of the element. `href` — the `href` attribute for links. `selector` — a CSS selector matching the element (e.g., `div.main > button.cta`).'
            ),
        operator: AssistantNumericValuePropertyFilterOperator,
        type: z
            .literal('element')
            .describe(
                'Filter by autocaptured HTML element properties (`$autocapture`, `$rageclick`). Example: `{ type: "element", key: "text", value: "Sign Up", operator: "exact" }`'
            )
            .default('element'),
        value: z.coerce.number(),
    }),
    z.object({
        key: z
            .enum(['tag_name', 'text', 'href', 'selector'])
            .describe(
                'The element property to filter on. `tag_name` — HTML tag (e.g., `button`, `a`, `input`). `text` — visible text content of the element. `href` — the `href` attribute for links. `selector` — a CSS selector matching the element (e.g., `div.main > button.cta`).'
            ),
        operator: AssistantArrayPropertyFilterOperator.describe(
            '`exact` - exact match of any of the values. `is_not` - does not match any of the values.'
        ),
        type: z
            .literal('element')
            .describe(
                'Filter by autocaptured HTML element properties (`$autocapture`, `$rageclick`). Example: `{ type: "element", key: "text", value: "Sign Up", operator: "exact" }`'
            )
            .default('element'),
        value: z
            .array(z.string())
            .describe(
                'Only use property values from the plan. Always use strings as values. If you have a number, convert it to a string first. If you have a boolean, convert it to a string "true" or "false".'
            ),
    }),
    z.object({
        key: z
            .enum(['tag_name', 'text', 'href', 'selector'])
            .describe(
                'The element property to filter on. `tag_name` — HTML tag (e.g., `button`, `a`, `input`). `text` — visible text content of the element. `href` — the `href` attribute for links. `selector` — a CSS selector matching the element (e.g., `div.main > button.cta`).'
            ),
        operator: AssistantDateTimePropertyFilterOperator,
        type: z
            .literal('element')
            .describe(
                'Filter by autocaptured HTML element properties (`$autocapture`, `$rageclick`). Example: `{ type: "element", key: "text", value: "Sign Up", operator: "exact" }`'
            )
            .default('element'),
        value: z.string().describe('Value must be a date in ISO 8601 format.'),
    }),
    z.object({
        key: z
            .enum(['tag_name', 'text', 'href', 'selector'])
            .describe(
                'The element property to filter on. `tag_name` — HTML tag (e.g., `button`, `a`, `input`). `text` — visible text content of the element. `href` — the `href` attribute for links. `selector` — a CSS selector matching the element (e.g., `div.main > button.cta`).'
            ),
        operator: AssistantSetPropertyFilterOperator.describe(
            "`is_set` - the property has any value. `is_not_set` - the property doesn't have a value or wasn't collected."
        ),
        type: z
            .literal('element')
            .describe(
                'Filter by autocaptured HTML element properties (`$autocapture`, `$rageclick`). Example: `{ type: "element", key: "text", value: "Sign Up", operator: "exact" }`'
            )
            .default('element'),
    }),
])

const AssistantHogQLPropertyFilter = z.object({
    key: z
        .string()
        .describe(
            "A HogQL boolean expression used as a filter condition.\n\nExamples:\n- Filter where a property exceeds a threshold: `toFloat(properties.load_time) > 5.0`\n- Filter with string matching: `properties.$current_url LIKE '%/pricing%'`\n- Filter with multiple conditions: `properties.$browser = 'Chrome' AND toFloat(properties.duration) > 30`"
        ),
    type: z
        .literal('hogql')
        .describe(
            "Filter by a HogQL boolean expression for advanced filtering that can't be expressed with standard property filters."
        )
        .default('hogql'),
})

const AssistantFlagPropertyFilter = z.object({
    key: z.string().describe('The feature flag key.'),
    operator: z.literal('flag_evaluates_to').default('flag_evaluates_to'),
    type: z
        .literal('flag')
        .describe(
            'Filter events by feature flag state — only include events where a specific flag evaluated to a given value. Examples:\n- Flag enabled: `{ type: "flag", key: "new-onboarding", operator: "flag_evaluates_to", value: true }`\n- Specific variant: `{ type: "flag", key: "checkout-experiment", operator: "flag_evaluates_to", value: "variant-a" }`'
        )
        .default('flag'),
    value: z
        .union([z.coerce.boolean(), z.string()])
        .describe('`true`/`false` for boolean flags, or a variant name string for multivariate flags.'),
})

const AssistantPropertyFilter = z.union([
    AssistantGenericPropertyFilter,
    AssistantGroupPropertyFilter,
    AssistantCohortPropertyFilter,
    AssistantElementPropertyFilter,
    AssistantHogQLPropertyFilter,
    AssistantFlagPropertyFilter,
])

const AssistantRecordingPropertyFilter = z.union([
    z.object({
        key: z
            .enum([
                'duration',
                'active_seconds',
                'inactive_seconds',
                'console_error_count',
                'console_log_count',
                'console_warn_count',
                'click_count',
                'keypress_count',
                'activity_score',
                'visited_page',
                'snapshot_source',
            ])
            .describe(
                'Recording metric to filter on.\n- `duration` — total recording duration in seconds.\n- `active_seconds` — seconds with user activity.\n- `inactive_seconds` — seconds without user activity.\n- `console_error_count` — number of console errors.\n- `console_log_count` — number of console log entries.\n- `console_warn_count` — number of console warnings.\n- `click_count` — number of clicks.\n- `keypress_count` — number of key presses.\n- `activity_score` — computed activity score (0-100).\n- `visited_page` — URL visited during the session.\n- `snapshot_source` — the recording source (e.g. "web", "mobile").'
            ),
        operator: AssistantStringOrBooleanValuePropertyFilterOperator.describe(
            '`icontains` - case insensitive contains. `not_icontains` - case insensitive does not contain. `regex` - matches the regex pattern. `not_regex` - does not match the regex pattern.'
        ),
        type: z.literal('recording').default('recording'),
        value: z
            .string()
            .describe(
                'Only use property values from the plan. If the operator is `regex` or `not_regex`, the value must be a valid ClickHouse regex pattern to match against. Otherwise, the value must be a substring that will be matched against the property value. Use the string values `true` or `false` for boolean properties.'
            ),
    }),
    z.object({
        key: z
            .enum([
                'duration',
                'active_seconds',
                'inactive_seconds',
                'console_error_count',
                'console_log_count',
                'console_warn_count',
                'click_count',
                'keypress_count',
                'activity_score',
                'visited_page',
                'snapshot_source',
            ])
            .describe(
                'Recording metric to filter on.\n- `duration` — total recording duration in seconds.\n- `active_seconds` — seconds with user activity.\n- `inactive_seconds` — seconds without user activity.\n- `console_error_count` — number of console errors.\n- `console_log_count` — number of console log entries.\n- `console_warn_count` — number of console warnings.\n- `click_count` — number of clicks.\n- `keypress_count` — number of key presses.\n- `activity_score` — computed activity score (0-100).\n- `visited_page` — URL visited during the session.\n- `snapshot_source` — the recording source (e.g. "web", "mobile").'
            ),
        operator: AssistantNumericValuePropertyFilterOperator,
        type: z.literal('recording').default('recording'),
        value: z.coerce.number(),
    }),
    z.object({
        key: z
            .enum([
                'duration',
                'active_seconds',
                'inactive_seconds',
                'console_error_count',
                'console_log_count',
                'console_warn_count',
                'click_count',
                'keypress_count',
                'activity_score',
                'visited_page',
                'snapshot_source',
            ])
            .describe(
                'Recording metric to filter on.\n- `duration` — total recording duration in seconds.\n- `active_seconds` — seconds with user activity.\n- `inactive_seconds` — seconds without user activity.\n- `console_error_count` — number of console errors.\n- `console_log_count` — number of console log entries.\n- `console_warn_count` — number of console warnings.\n- `click_count` — number of clicks.\n- `keypress_count` — number of key presses.\n- `activity_score` — computed activity score (0-100).\n- `visited_page` — URL visited during the session.\n- `snapshot_source` — the recording source (e.g. "web", "mobile").'
            ),
        operator: AssistantArrayPropertyFilterOperator.describe(
            '`exact` - exact match of any of the values. `is_not` - does not match any of the values.'
        ),
        type: z.literal('recording').default('recording'),
        value: z
            .array(z.string())
            .describe(
                'Only use property values from the plan. Always use strings as values. If you have a number, convert it to a string first. If you have a boolean, convert it to a string "true" or "false".'
            ),
    }),
    z.object({
        key: z
            .enum([
                'duration',
                'active_seconds',
                'inactive_seconds',
                'console_error_count',
                'console_log_count',
                'console_warn_count',
                'click_count',
                'keypress_count',
                'activity_score',
                'visited_page',
                'snapshot_source',
            ])
            .describe(
                'Recording metric to filter on.\n- `duration` — total recording duration in seconds.\n- `active_seconds` — seconds with user activity.\n- `inactive_seconds` — seconds without user activity.\n- `console_error_count` — number of console errors.\n- `console_log_count` — number of console log entries.\n- `console_warn_count` — number of console warnings.\n- `click_count` — number of clicks.\n- `keypress_count` — number of key presses.\n- `activity_score` — computed activity score (0-100).\n- `visited_page` — URL visited during the session.\n- `snapshot_source` — the recording source (e.g. "web", "mobile").'
            ),
        operator: AssistantDateTimePropertyFilterOperator,
        type: z.literal('recording').default('recording'),
        value: z.string().describe('Value must be a date in ISO 8601 format.'),
    }),
    z.object({
        key: z
            .enum([
                'duration',
                'active_seconds',
                'inactive_seconds',
                'console_error_count',
                'console_log_count',
                'console_warn_count',
                'click_count',
                'keypress_count',
                'activity_score',
                'visited_page',
                'snapshot_source',
            ])
            .describe(
                'Recording metric to filter on.\n- `duration` — total recording duration in seconds.\n- `active_seconds` — seconds with user activity.\n- `inactive_seconds` — seconds without user activity.\n- `console_error_count` — number of console errors.\n- `console_log_count` — number of console log entries.\n- `console_warn_count` — number of console warnings.\n- `click_count` — number of clicks.\n- `keypress_count` — number of key presses.\n- `activity_score` — computed activity score (0-100).\n- `visited_page` — URL visited during the session.\n- `snapshot_source` — the recording source (e.g. "web", "mobile").'
            ),
        operator: AssistantSetPropertyFilterOperator.describe(
            "`is_set` - the property has any value. `is_not_set` - the property doesn't have a value or wasn't collected."
        ),
        type: z.literal('recording').default('recording'),
    }),
])

const AssistantRecordingsQueryPropertyFilter = z.union([AssistantPropertyFilter, AssistantRecordingPropertyFilter])

const AssistantRecordingsQuery = z.object({
    after: z.string().describe("Cursor for pagination from a previous response's next_cursor field.").optional(),
    date_from: z
        .string()
        .nullable()
        .describe(
            'Start of the date range. Supports relative dates like "-7d", "-24h" or ISO 8601 format. Default: "-3d".'
        )
        .optional(),
    date_to: z
        .string()
        .nullable()
        .describe('End of the date range. Supports relative dates or ISO 8601 format. Default: now.')
        .optional(),
    filter_test_accounts: z.coerce.boolean().describe('Exclude internal and test users. Default: false.').optional(),
    kind: z.literal('RecordingsQuery').default('RecordingsQuery'),
    limit: integer.describe('Maximum number of recordings to return.').optional(),
    order: RecordingOrder.describe(
        'Sort field. Options: "start_time", "duration", "activity_score", "console_error_count", "click_count". Default: "start_time".'
    ).optional(),
    order_direction: RecordingOrderDirection.describe('Sort direction: "ASC" or "DESC". Default: "DESC".').optional(),
    person_uuid: z.string().describe('Filter recordings to a specific person by their UUID.').optional(),
    properties: z
        .array(AssistantRecordingsQueryPropertyFilter)
        .describe(
            'Property filters to narrow results. Each filter has a `key`, `value`, `operator`, and `type`.\n\nSupported types:\n- `person`: Filter by person properties (e.g. email, country).\n- `session`: Filter by session properties (e.g. $session_duration, $channel_type, $entry_current_url).\n- `event`: Filter by properties of events in the session (e.g. $current_url, $browser).\n- `recording`: Filter by recording metrics (e.g. console_error_count, click_count, activity_score).\n- `cohort`: Filter recordings to persons belonging to a cohort. Example: `{ type: "cohort", key: "id", value: 42, operator: "in" }`.'
        )
        .optional(),
    session_ids: z
        .array(z.string())
        .describe(
            'Filter to specific session recording IDs. Use this when you have known session IDs (e.g., from $session_id on events) to fetch multiple recordings in a single call.'
        )
        .optional(),
})

export const GENERATED_TOOLS: Record<string, () => ToolBase<ZodObjectAny>> = {
    'session-recording-get': sessionRecordingGet,
    'session-recording-delete': sessionRecordingDelete,
    'session-recording-playlists-list': sessionRecordingPlaylistsList,
    'session-recording-playlist-get': sessionRecordingPlaylistGet,
    'session-recording-playlist-create': sessionRecordingPlaylistCreate,
    'session-recording-playlist-update': sessionRecordingPlaylistUpdate,
    'query-session-recordings-list': createQueryWrapper({
        name: 'query-session-recordings-list',
        schema: AssistantRecordingsQuery,
        kind: 'RecordingsQuery',
        urlPrefix: '/replay',
        mcpVersion: 2,
    }),
}
