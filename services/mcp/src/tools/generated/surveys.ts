// AUTO-GENERATED from products/surveys/mcp/tools.yaml + OpenAPI — do not edit
import { z } from 'zod'

import type { Schemas } from '@/api/generated'
import {
    SurveysCreateBody,
    SurveysDestroyParams,
    SurveysListQueryParams,
    SurveysPartialUpdateBody,
    SurveysPartialUpdateParams,
    SurveysRetrieveParams,
    SurveysStatsRetrieve2Params,
    SurveysStatsRetrieve2QueryParams,
    SurveysStatsRetrieveQueryParams,
} from '@/generated/surveys/api'
import { withUiApp } from '@/resources/ui-apps'
import { withPostHogUrl, type WithPostHogUrl } from '@/tools/tool-utils'
import type { Context, ToolBase, ZodObjectAny } from '@/tools/types'

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

const SurveyCreateSchema = SurveysCreateBody.omit({
    schedule: true,
    linked_insight_id: true,
    targeting_flag_id: true,
    remove_targeting_flag: true,
    conditions: true,
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
    enable_iframe_embedding: true,
    translations: true,
    _create_in_folder: true,
    form_content: true,
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
            if (params.linked_flag_id !== undefined) {
                body['linked_flag_id'] = params.linked_flag_id
            }
            if (params.targeting_flag_filters !== undefined) {
                body['targeting_flag_filters'] = params.targeting_flag_filters
            }
            if (params.questions !== undefined) {
                body['questions'] = params.questions
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
            const result = await context.api.request<Schemas.SurveySerializerCreateUpdateOnly>({
                method: 'POST',
                path: `/api/projects/${encodeURIComponent(String(projectId))}/surveys/`,
                body,
            })
            return await withPostHogUrl(context, result, `/surveys/${result.id}`)
        },
    })

const SurveyUpdateSchema = SurveysPartialUpdateParams.omit({ project_id: true }).extend(
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
        enable_iframe_embedding: true,
        translations: true,
        _create_in_folder: true,
        form_content: true,
    }).shape
)

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
            const result = await context.api.request<Schemas.SurveySerializerCreateUpdateOnly>({
                method: 'PATCH',
                path: `/api/projects/${encodeURIComponent(String(projectId))}/surveys/${encodeURIComponent(String(params.id))}/`,
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

const SurveyStatsSchema = SurveysStatsRetrieve2Params.omit({ project_id: true }).extend(
    SurveysStatsRetrieve2QueryParams.shape
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

const SurveysGlobalStatsSchema = SurveysStatsRetrieveQueryParams

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
    'surveys-get-all': surveysGetAll,
    'survey-get': surveyGet,
    'survey-create': surveyCreate,
    'survey-update': surveyUpdate,
    'survey-delete': surveyDelete,
    'survey-stats': surveyStats,
    'surveys-global-stats': surveysGlobalStats,
}
