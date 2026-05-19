// AUTO-GENERATED from products/surveys/mcp/tools.yaml + OpenAPI — do not edit
import { z } from 'zod'

import type { Schemas } from '@/api/generated'
import {
    SurveysCreateBody,
    SurveysDestroyParams,
    SurveysGlobalStatsRetrieveQueryParams,
    SurveysListQueryParams,
    SurveysPartialUpdateBody,
    SurveysPartialUpdateParams,
    SurveysRetrieveParams,
    SurveysStatsRetrieveParams,
    SurveysStatsRetrieveQueryParams,
} from '@/generated/surveys/api'
import { withUiApp } from '@/resources/ui-apps'
import { withPostHogUrl, type WithPostHogUrl } from '@/tools/tool-utils'
import type { Context, ToolBase, ZodObjectAny } from '@/tools/types'

const SurveyCreateSchema = SurveysCreateBody.omit({
    linked_insight_id: true,
    targeting_flag_id: true,
    remove_targeting_flag: true,
    end_date: true,
    archived: true,
    iteration_start_dates: true,
    current_iteration: true,
    current_iteration_start_date: true,
    response_sampling_start_date: true,
    response_sampling_interval_type: true,
    response_sampling_interval: true,
    response_sampling_limit: true,
    response_sampling_daily_limits: true,
    _create_in_folder: true,
}).extend({
    type: SurveysCreateBody.shape['type'].describe(
        'Survey type. Use popover for most in-app surveys, widget for always-available feedback entrypoints, external_survey for hosted forms with a shareable public URL, and api only for headless custom implementations.'
    ),
    schedule: SurveysCreateBody.shape['schedule'].describe(
        'Survey scheduling behavior. Omit this to use the default once behavior. Use recurring only when the user explicitly asks for a repeated schedule.'
    ),
    questions: SurveysCreateBody.shape['questions'].describe(
        'Complete survey question list. Prefer 1-3 questions unless the user explicitly asks for a longer survey. Use rating questions for NPS/CSAT, open for freeform feedback, and choice questions when the user wants structured answers. Questions can include inline translations on each question.'
    ),
    conditions: SurveysCreateBody.shape['conditions'].describe(
        'Display and targeting conditions for in-app surveys, such as URL matching, event triggers, device filters, or linked flag variants. Do not use URL, selector, event, device, or linkedFlagVariant conditions for external_survey forms.'
    ),
    start_date: SurveysCreateBody.shape['start_date'].describe(
        'Setting this launches the survey immediately. Leave unset unless the user explicitly asks to launch now.'
    ),
    linked_flag_id: SurveysCreateBody.shape['linked_flag_id'].describe(
        'Feature flag ID linked to this survey. Use only when the user explicitly wants the survey linked to a feature flag. Resolve the flag ID first, preferably with SQL in v2.'
    ),
    targeting_flag_filters: SurveysCreateBody.shape['targeting_flag_filters'].describe(
        'User targeting rules for in-app surveys. Use only when the user wants the survey shown to a subset of users. Do not use this for external_survey forms.'
    ),
    enable_iframe_embedding: SurveysCreateBody.shape['enable_iframe_embedding'].describe(
        'Allows an external_survey form to be embedded in an iframe. Use only when the user explicitly asks for iframe embedding.'
    ),
    translations: SurveysCreateBody.shape['translations'].describe(
        "Optional survey-level translations keyed by language code. Use for translated survey name, description, and thank-you message fields. Question text translations belong inside each question's translations object."
    ),
    form_content: SurveysCreateBody.shape['form_content'].describe(
        'Optional hosted-form content configuration for external_survey forms. Only include this when the user explicitly asks to customize the hosted form content beyond the standard question flow.'
    ),
})

const surveyCreate = (): ToolBase<
    typeof SurveyCreateSchema,
    WithPostHogUrl<Schemas.SurveySerializerCreateUpdateOnly>
> =>
    withUiApp('survey', {
        name: 'survey-create',
        schema: SurveyCreateSchema,
        handler: async (context: Context, params: z.infer<typeof SurveyCreateSchema>) => {
            const projectId = await context.stateManager.getProjectId()
            const body: Record<string, unknown> = {}
            if (params.name !== undefined) {
                body['name'] = params.name
            }
            if (params.description !== undefined) {
                body['description'] = params.description
            }
            if (params.type !== undefined) {
                body['type'] = params.type
            }
            if (params.schedule !== undefined) {
                body['schedule'] = params.schedule
            }
            if (params.linked_flag_id !== undefined) {
                body['linked_flag_id'] = params.linked_flag_id
            }
            if (params.targeting_flag_filters !== undefined) {
                body['targeting_flag_filters'] = params.targeting_flag_filters
            }
            if (params.questions !== undefined) {
                body['questions'] = params.questions
            }
            if (params.conditions !== undefined) {
                body['conditions'] = params.conditions
            }
            if (params.appearance !== undefined) {
                body['appearance'] = params.appearance
            }
            if (params.start_date !== undefined) {
                body['start_date'] = params.start_date
            }
            if (params.responses_limit !== undefined) {
                body['responses_limit'] = params.responses_limit
            }
            if (params.iteration_count !== undefined) {
                body['iteration_count'] = params.iteration_count
            }
            if (params.iteration_frequency_days !== undefined) {
                body['iteration_frequency_days'] = params.iteration_frequency_days
            }
            if (params.enable_partial_responses !== undefined) {
                body['enable_partial_responses'] = params.enable_partial_responses
            }
            if (params.enable_iframe_embedding !== undefined) {
                body['enable_iframe_embedding'] = params.enable_iframe_embedding
            }
            if (params.translations !== undefined) {
                body['translations'] = params.translations
            }
            if (params.form_content !== undefined) {
                body['form_content'] = params.form_content
            }
            const result = await context.api.request<Schemas.SurveySerializerCreateUpdateOnly>({
                method: 'POST',
                path: `/api/projects/${encodeURIComponent(String(projectId))}/surveys/`,
                body,
            })
            return await withPostHogUrl(context, result, `/surveys/${result.id}`)
        },
    })

const SurveyDeleteSchema = SurveysDestroyParams.omit({ project_id: true })

const surveyDelete = (): ToolBase<typeof SurveyDeleteSchema, Schemas.SurveySerializerCreateUpdateOnly> => ({
    name: 'survey-delete',
    schema: SurveyDeleteSchema,
    handler: async (context: Context, params: z.infer<typeof SurveyDeleteSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.SurveySerializerCreateUpdateOnly>({
            method: 'PATCH',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/surveys/${encodeURIComponent(String(params.id))}/`,
            body: { archived: true },
        })
        return result
    },
})

const SurveyGetSchema = SurveysRetrieveParams.omit({ project_id: true })

const surveyGet = (): ToolBase<typeof SurveyGetSchema, WithPostHogUrl<Schemas.Survey>> =>
    withUiApp('survey', {
        name: 'survey-get',
        schema: SurveyGetSchema,
        handler: async (context: Context, params: z.infer<typeof SurveyGetSchema>) => {
            const projectId = await context.stateManager.getProjectId()
            const result = await context.api.request<Schemas.Survey>({
                method: 'GET',
                path: `/api/projects/${encodeURIComponent(String(projectId))}/surveys/${encodeURIComponent(String(params.id))}/`,
            })
            return await withPostHogUrl(context, result, `/surveys/${result.id}`)
        },
    })

const SurveyStatsSchema = SurveysStatsRetrieveParams.omit({ project_id: true }).extend(
    SurveysStatsRetrieveQueryParams.shape
)

const surveyStats = (): ToolBase<typeof SurveyStatsSchema, WithPostHogUrl<Schemas.SurveyStatsResponse>> =>
    withUiApp('survey-stats', {
        name: 'survey-stats',
        schema: SurveyStatsSchema,
        handler: async (context: Context, params: z.infer<typeof SurveyStatsSchema>) => {
            const projectId = await context.stateManager.getProjectId()
            const result = await context.api.request<Schemas.SurveyStatsResponse>({
                method: 'GET',
                path: `/api/projects/${encodeURIComponent(String(projectId))}/surveys/${encodeURIComponent(String(params.id))}/stats/`,
                query: {
                    date_from: params.date_from,
                    date_to: params.date_to,
                },
            })
            return await withPostHogUrl(context, result, `/surveys/${result.survey_id}`)
        },
    })

const SurveyUpdateSchema = SurveysPartialUpdateParams.omit({ project_id: true })
    .extend(
        SurveysPartialUpdateBody.omit({
            linked_insight_id: true,
            iteration_start_dates: true,
            current_iteration: true,
            current_iteration_start_date: true,
            response_sampling_start_date: true,
            response_sampling_interval_type: true,
            response_sampling_interval: true,
            response_sampling_limit: true,
            response_sampling_daily_limits: true,
            _create_in_folder: true,
        }).shape
    )
    .extend({
        questions: SurveysPartialUpdateBody.shape['questions'].describe(
            "Complete replacement question list. Existing question IDs are tied to response data and must be preserved. Before sending this field, fetch the survey first, modify the existing question objects in place, keep every unchanged or edited question's id, and include the complete intended ordered question list. New questions should omit id. Do not regenerate existing questions from scratch."
        ),
        conditions: SurveysPartialUpdateBody.shape['conditions'].describe(
            'Complete replacement display and targeting conditions object. Do not provide this field unless changing display targeting. Preserve existing URL, selector, event, device, wait-period, and linked flag variant conditions unless explicitly changing them.'
        ),
        translations: SurveysPartialUpdateBody.shape['translations'].describe(
            'Complete replacement survey-level translations object. Do not provide this field unless changing translations. Preserve existing language keys and translated fields that should remain. Use null only when the user explicitly asks to remove survey-level translations.'
        ),
        form_content: SurveysPartialUpdateBody.shape['form_content'].describe(
            'Hosted-form content configuration for external_survey forms. Do not provide this field unless editing hosted-form content. Preserve existing content fields that should remain.'
        ),
    })

const surveyUpdate = (): ToolBase<
    typeof SurveyUpdateSchema,
    WithPostHogUrl<Schemas.SurveySerializerCreateUpdateOnly>
> =>
    withUiApp('survey', {
        name: 'survey-update',
        schema: SurveyUpdateSchema,
        handler: async (context: Context, params: z.infer<typeof SurveyUpdateSchema>) => {
            const projectId = await context.stateManager.getProjectId()
            const body: Record<string, unknown> = {}
            if (params.name !== undefined) {
                body['name'] = params.name
            }
            if (params.description !== undefined) {
                body['description'] = params.description
            }
            if (params.type !== undefined) {
                body['type'] = params.type
            }
            if (params.schedule !== undefined) {
                body['schedule'] = params.schedule
            }
            if (params.linked_flag_id !== undefined) {
                body['linked_flag_id'] = params.linked_flag_id
            }
            if (params.targeting_flag_id !== undefined) {
                body['targeting_flag_id'] = params.targeting_flag_id
            }
            if (params.targeting_flag_filters !== undefined) {
                body['targeting_flag_filters'] = params.targeting_flag_filters
            }
            if (params.remove_targeting_flag !== undefined) {
                body['remove_targeting_flag'] = params.remove_targeting_flag
            }
            if (params.questions !== undefined) {
                body['questions'] = params.questions
            }
            if (params.conditions !== undefined) {
                body['conditions'] = params.conditions
            }
            if (params.appearance !== undefined) {
                body['appearance'] = params.appearance
            }
            if (params.start_date !== undefined) {
                body['start_date'] = params.start_date
            }
            if (params.end_date !== undefined) {
                body['end_date'] = params.end_date
            }
            if (params.archived !== undefined) {
                body['archived'] = params.archived
            }
            if (params.responses_limit !== undefined) {
                body['responses_limit'] = params.responses_limit
            }
            if (params.iteration_count !== undefined) {
                body['iteration_count'] = params.iteration_count
            }
            if (params.iteration_frequency_days !== undefined) {
                body['iteration_frequency_days'] = params.iteration_frequency_days
            }
            if (params.enable_partial_responses !== undefined) {
                body['enable_partial_responses'] = params.enable_partial_responses
            }
            if (params.enable_iframe_embedding !== undefined) {
                body['enable_iframe_embedding'] = params.enable_iframe_embedding
            }
            if (params.translations !== undefined) {
                body['translations'] = params.translations
            }
            if (params.form_content !== undefined) {
                body['form_content'] = params.form_content
            }
            const result = await context.api.request<Schemas.SurveySerializerCreateUpdateOnly>({
                method: 'PATCH',
                path: `/api/projects/${encodeURIComponent(String(projectId))}/surveys/${encodeURIComponent(String(params.id))}/`,
                body,
            })
            return await withPostHogUrl(context, result, `/surveys/${result.id}`)
        },
    })

const SurveysGetAllSchema = SurveysListQueryParams

const surveysGetAll = (): ToolBase<typeof SurveysGetAllSchema, WithPostHogUrl<Schemas.PaginatedSurveyList>> =>
    withUiApp('survey-list', {
        name: 'surveys-get-all',
        schema: SurveysGetAllSchema,
        handler: async (context: Context, params: z.infer<typeof SurveysGetAllSchema>) => {
            const projectId = await context.stateManager.getProjectId()
            const result = await context.api.request<Schemas.PaginatedSurveyList>({
                method: 'GET',
                path: `/api/projects/${encodeURIComponent(String(projectId))}/surveys/`,
                query: {
                    archived: params.archived,
                    limit: params.limit,
                    offset: params.offset,
                    search: params.search,
                },
            })
            return await withPostHogUrl(
                context,
                {
                    ...result,
                    results: await Promise.all(
                        (result.results ?? []).map((item) => withPostHogUrl(context, item, `/surveys/${item.id}`))
                    ),
                },
                '/surveys'
            )
        },
    })

const SurveysGlobalStatsSchema = SurveysGlobalStatsRetrieveQueryParams

const surveysGlobalStats = (): ToolBase<typeof SurveysGlobalStatsSchema, Schemas.SurveyGlobalStatsResponse> =>
    withUiApp('survey-global-stats', {
        name: 'surveys-global-stats',
        schema: SurveysGlobalStatsSchema,
        handler: async (context: Context, params: z.infer<typeof SurveysGlobalStatsSchema>) => {
            const projectId = await context.stateManager.getProjectId()
            const result = await context.api.request<Schemas.SurveyGlobalStatsResponse>({
                method: 'GET',
                path: `/api/projects/${encodeURIComponent(String(projectId))}/surveys/stats/`,
                query: {
                    date_from: params.date_from,
                    date_to: params.date_to,
                },
            })
            return result
        },
    })

export const GENERATED_TOOLS: Record<string, () => ToolBase<ZodObjectAny>> = {
    'survey-create': surveyCreate,
    'survey-delete': surveyDelete,
    'survey-get': surveyGet,
    'survey-stats': surveyStats,
    'survey-update': surveyUpdate,
    'surveys-get-all': surveysGetAll,
    'surveys-global-stats': surveysGlobalStats,
}
