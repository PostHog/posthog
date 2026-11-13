// AUTO-GENERATED from products/aeo/mcp/tools.yaml + OpenAPI — do not edit
import { z } from 'zod'

import type { Schemas } from '@/api/generated'
import * as orvalSchemas from '@/generated/aeo/api'
import { withPostHogUrl, type WithPostHogUrl } from '@/tools/tool-utils'
import type { Context, ToolBase, ZodObjectAny } from '@/tools/types'

const AeoBrandsCreateSchema = () => {
    const AeoBrandsCreateBody = orvalSchemas.AeoBrandsCreateBody()
    return AeoBrandsCreateBody
}

const aeoBrandsCreate = (): ToolBase<ReturnType<typeof AeoBrandsCreateSchema>, Schemas.AEOBrand> => ({
    name: 'aeo-brands-create',
    schema: AeoBrandsCreateSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof AeoBrandsCreateSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.domain !== undefined) {
            body['domain'] = params.domain
        }
        if (params.name !== undefined) {
            body['name'] = params.name
        }
        if (params.kind !== undefined) {
            body['kind'] = params.kind
        }
        if (params.aliases !== undefined) {
            body['aliases'] = params.aliases
        }
        const result = await context.api.request<Schemas.AEOBrand>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/aeo_brands/`,
            body,
        })
        return result
    },
})

const AeoBrandsGetSchema = () => {
    const AeoBrandsRetrieveParams = orvalSchemas.AeoBrandsRetrieveParams()
    return AeoBrandsRetrieveParams.omit({ project_id: true }).extend({
        id: AeoBrandsRetrieveParams.shape['id'].describe('The brand id (a UUID), from `aeo-brands-list`.'),
    })
}

const aeoBrandsGet = (): ToolBase<ReturnType<typeof AeoBrandsGetSchema>, Schemas.AEOBrand> => ({
    name: 'aeo-brands-get',
    schema: AeoBrandsGetSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof AeoBrandsGetSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.AEOBrand>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/aeo_brands/${encodeURIComponent(String(params.id))}/`,
        })
        return result
    },
})

const AeoBrandsListSchema = () => {
    const AeoBrandsListQueryParams = orvalSchemas.AeoBrandsListQueryParams()
    return AeoBrandsListQueryParams
}

const aeoBrandsList = (): ToolBase<
    ReturnType<typeof AeoBrandsListSchema>,
    WithPostHogUrl<Schemas.PaginatedAEOBrandList>
> => ({
    name: 'aeo-brands-list',
    schema: AeoBrandsListSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof AeoBrandsListSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.PaginatedAEOBrandList>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/aeo_brands/`,
            query: {
                kind: params.kind,
                limit: params.limit,
                offset: params.offset,
                search: params.search,
                status: params.status,
            },
        })
        return await withPostHogUrl(context, result, '/web/ai-visibility')
    },
})

const AeoBrandsUpdateSchema = () => {
    const AeoBrandsPartialUpdateBody = orvalSchemas.AeoBrandsPartialUpdateBody()
    const AeoBrandsPartialUpdateParams = orvalSchemas.AeoBrandsPartialUpdateParams()
    return AeoBrandsPartialUpdateParams.omit({ project_id: true })
        .extend(AeoBrandsPartialUpdateBody.shape)
        .extend({
            id: AeoBrandsPartialUpdateParams.shape['id'].describe('The brand id (a UUID), from `aeo-brands-list`.'),
        })
}

const aeoBrandsUpdate = (): ToolBase<ReturnType<typeof AeoBrandsUpdateSchema>, Schemas.AEOBrand> => ({
    name: 'aeo-brands-update',
    schema: AeoBrandsUpdateSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof AeoBrandsUpdateSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.name !== undefined) {
            body['name'] = params.name
        }
        if (params.kind !== undefined) {
            body['kind'] = params.kind
        }
        if (params.status !== undefined) {
            body['status'] = params.status
        }
        if (params.aliases !== undefined) {
            body['aliases'] = params.aliases
        }
        const result = await context.api.request<Schemas.AEOBrand>({
            method: 'PATCH',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/aeo_brands/${encodeURIComponent(String(params.id))}/`,
            body,
        })
        return result
    },
})

const AeoEnginesListSchema = () => z.object({})

const aeoEnginesList = (): ToolBase<ReturnType<typeof AeoEnginesListSchema>, Schemas.AEOEngineSetting[]> => ({
    name: 'aeo-engines-list',
    schema: AeoEnginesListSchema(),
    handler: async (context: Context, _params: z.infer<ReturnType<typeof AeoEnginesListSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.AEOEngineSetting[]>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/aeo_engines/`,
        })
        return result
    },
})

const AeoEnginesUpdateSchema = () => {
    const AeoEnginesPartialUpdateBody = orvalSchemas.AeoEnginesPartialUpdateBody()
    const AeoEnginesPartialUpdateParams = orvalSchemas.AeoEnginesPartialUpdateParams()
    return AeoEnginesPartialUpdateParams.omit({ project_id: true }).extend(AeoEnginesPartialUpdateBody.shape)
}

const aeoEnginesUpdate = (): ToolBase<ReturnType<typeof AeoEnginesUpdateSchema>, Schemas.AEOEngineSetting> => ({
    name: 'aeo-engines-update',
    schema: AeoEnginesUpdateSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof AeoEnginesUpdateSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.enabled !== undefined) {
            body['enabled'] = params.enabled
        }
        if (params.frequency !== undefined) {
            body['frequency'] = params.frequency
        }
        const result = await context.api.request<Schemas.AEOEngineSetting>({
            method: 'PATCH',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/aeo_engines/${encodeURIComponent(String(params.id))}/`,
            body,
        })
        return result
    },
})

const AeoKeywordsCreateSchema = () => {
    const AeoKeywordsCreateBody = orvalSchemas.AeoKeywordsCreateBody()
    return AeoKeywordsCreateBody
}

const aeoKeywordsCreate = (): ToolBase<ReturnType<typeof AeoKeywordsCreateSchema>, Schemas.AEOKeywordCreateResult> => ({
    name: 'aeo-keywords-create',
    schema: AeoKeywordsCreateSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof AeoKeywordsCreateSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.keywords !== undefined) {
            body['keywords'] = params.keywords
        }
        const result = await context.api.request<Schemas.AEOKeywordCreateResult>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/aeo_keywords/`,
            body,
        })
        return result
    },
})

const AeoKeywordsDeleteSchema = () => {
    const AeoKeywordsDestroyParams = orvalSchemas.AeoKeywordsDestroyParams()
    return AeoKeywordsDestroyParams.omit({ project_id: true }).extend({
        id: AeoKeywordsDestroyParams.shape['id'].describe('The keyword id (a UUID), from `aeo-keywords-list`.'),
    })
}

const aeoKeywordsDelete = (): ToolBase<ReturnType<typeof AeoKeywordsDeleteSchema>, unknown> => ({
    name: 'aeo-keywords-delete',
    schema: AeoKeywordsDeleteSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof AeoKeywordsDeleteSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<unknown>({
            method: 'DELETE',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/aeo_keywords/${encodeURIComponent(String(params.id))}/`,
        })
        return result
    },
})

const AeoKeywordsGetSchema = () => {
    const AeoKeywordsRetrieveParams = orvalSchemas.AeoKeywordsRetrieveParams()
    return AeoKeywordsRetrieveParams.omit({ project_id: true }).extend({
        id: AeoKeywordsRetrieveParams.shape['id'].describe('The keyword id (a UUID), from `aeo-keywords-list`.'),
    })
}

const aeoKeywordsGet = (): ToolBase<ReturnType<typeof AeoKeywordsGetSchema>, Schemas.AEOKeyword> => ({
    name: 'aeo-keywords-get',
    schema: AeoKeywordsGetSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof AeoKeywordsGetSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.AEOKeyword>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/aeo_keywords/${encodeURIComponent(String(params.id))}/`,
        })
        return result
    },
})

const AeoKeywordsListSchema = () => z.object({})

const aeoKeywordsList = (): ToolBase<ReturnType<typeof AeoKeywordsListSchema>, Schemas.AEOKeyword[]> => ({
    name: 'aeo-keywords-list',
    schema: AeoKeywordsListSchema(),
    handler: async (context: Context, _params: z.infer<ReturnType<typeof AeoKeywordsListSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.AEOKeyword[]>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/aeo_keywords/`,
        })
        return result
    },
})

const AeoKeywordsModifiersGetSchema = () => {
    const AeoKeywordsModifiersQueryParams = orvalSchemas.AeoKeywordsModifiersQueryParams()
    return AeoKeywordsModifiersQueryParams
}

const aeoKeywordsModifiersGet = (): ToolBase<
    ReturnType<typeof AeoKeywordsModifiersGetSchema>,
    Schemas.AEOKeywordModifierReport
> => ({
    name: 'aeo-keywords-modifiers-get',
    schema: AeoKeywordsModifiersGetSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof AeoKeywordsModifiersGetSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.AEOKeywordModifierReport>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/aeo_keywords/modifiers/`,
            query: {
                days: params.days,
                keyword: params.keyword,
            },
        })
        return result
    },
})

const AeoKeywordsReportGetSchema = () => {
    const AeoKeywordsReportQueryParams = orvalSchemas.AeoKeywordsReportQueryParams()
    return AeoKeywordsReportQueryParams
}

const aeoKeywordsReportGet = (): ToolBase<ReturnType<typeof AeoKeywordsReportGetSchema>, Schemas.AEOKeywordReport> => ({
    name: 'aeo-keywords-report-get',
    schema: AeoKeywordsReportGetSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof AeoKeywordsReportGetSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.AEOKeywordReport>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/aeo_keywords/report/`,
            query: {
                days: params.days,
            },
        })
        return result
    },
})

const AeoKeywordsSuggestSchema = () => {
    const AeoKeywordsSuggestBody = orvalSchemas.AeoKeywordsSuggestBody()
    return AeoKeywordsSuggestBody
}

const aeoKeywordsSuggest = (): ToolBase<ReturnType<typeof AeoKeywordsSuggestSchema>, unknown> => ({
    name: 'aeo-keywords-suggest',
    schema: AeoKeywordsSuggestSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof AeoKeywordsSuggestSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.domain !== undefined) {
            body['domain'] = params.domain
        }
        if (params.brand !== undefined) {
            body['brand'] = params.brand
        }
        if (params.description !== undefined) {
            body['description'] = params.description
        }
        if (params.count !== undefined) {
            body['count'] = params.count
        }
        const result = await context.api.request<unknown>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/aeo_keywords/suggest/`,
            body,
        })
        return result
    },
})

const AeoKeywordsSuggestionGetSchema = () => {
    const AeoKeywordsSuggestionRetrieveParams = orvalSchemas.AeoKeywordsSuggestionRetrieveParams()
    return AeoKeywordsSuggestionRetrieveParams.omit({ project_id: true })
}

const aeoKeywordsSuggestionGet = (): ToolBase<
    ReturnType<typeof AeoKeywordsSuggestionGetSchema>,
    Schemas.AEOKeywordSuggestionJob
> => ({
    name: 'aeo-keywords-suggestion-get',
    schema: AeoKeywordsSuggestionGetSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof AeoKeywordsSuggestionGetSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.AEOKeywordSuggestionJob>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/aeo_keywords/suggest/${encodeURIComponent(String(params.job_id))}/`,
        })
        return result
    },
})

const AeoPromptsArchiveSchema = () => {
    const AeoPromptsDestroyParams = orvalSchemas.AeoPromptsDestroyParams()
    return AeoPromptsDestroyParams.omit({ project_id: true }).extend({
        id: AeoPromptsDestroyParams.shape['id'].describe('The prompt id (a UUID), from `aeo-prompts-list`.'),
    })
}

const aeoPromptsArchive = (): ToolBase<ReturnType<typeof AeoPromptsArchiveSchema>, unknown> => ({
    name: 'aeo-prompts-archive',
    schema: AeoPromptsArchiveSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof AeoPromptsArchiveSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<unknown>({
            method: 'DELETE',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/aeo_prompts/${encodeURIComponent(String(params.id))}/`,
        })
        return result
    },
})

const AeoPromptsChecksListSchema = () => {
    const AeoPromptsChecksParams = orvalSchemas.AeoPromptsChecksParams()
    const AeoPromptsChecksQueryParams = orvalSchemas.AeoPromptsChecksQueryParams()
    return AeoPromptsChecksParams.omit({ project_id: true })
        .extend(AeoPromptsChecksQueryParams.shape)
        .extend({ id: AeoPromptsChecksParams.shape['id'].describe('The prompt id (a UUID), from `aeo-prompts-list`.') })
}

const aeoPromptsChecksList = (): ToolBase<
    ReturnType<typeof AeoPromptsChecksListSchema>,
    WithPostHogUrl<Schemas.PaginatedAEOPromptCheckList>
> => ({
    name: 'aeo-prompts-checks-list',
    schema: AeoPromptsChecksListSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof AeoPromptsChecksListSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.PaginatedAEOPromptCheckList>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/aeo_prompts/${encodeURIComponent(String(params.id))}/checks/`,
            query: {
                engine: params.engine,
                include_answer_text: params.include_answer_text,
                limit: params.limit,
                offset: params.offset,
                since: params.since,
                version: params.version,
            },
        })
        return await withPostHogUrl(context, result, '/web/ai-visibility')
    },
})

const AeoPromptsCreateDashboardSchema = () => z.object({})

const aeoPromptsCreateDashboard = (): ToolBase<
    ReturnType<typeof AeoPromptsCreateDashboardSchema>,
    Schemas.AEOVisibilityDashboard
> => ({
    name: 'aeo-prompts-create-dashboard',
    schema: AeoPromptsCreateDashboardSchema(),
    handler: async (context: Context, _params: z.infer<ReturnType<typeof AeoPromptsCreateDashboardSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.AEOVisibilityDashboard>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/aeo_prompts/create_dashboard/`,
        })
        return result
    },
})

const AeoPromptsGetSchema = () => {
    const AeoPromptsRetrieveParams = orvalSchemas.AeoPromptsRetrieveParams()
    return AeoPromptsRetrieveParams.omit({ project_id: true }).extend({
        id: AeoPromptsRetrieveParams.shape['id'].describe('The prompt id (a UUID), from `aeo-prompts-list`.'),
    })
}

const aeoPromptsGet = (): ToolBase<ReturnType<typeof AeoPromptsGetSchema>, WithPostHogUrl<Schemas.AEOPrompt>> => ({
    name: 'aeo-prompts-get',
    schema: AeoPromptsGetSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof AeoPromptsGetSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.AEOPrompt>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/aeo_prompts/${encodeURIComponent(String(params.id))}/`,
        })
        return await withPostHogUrl(context, result, `/web/ai-visibility/prompts/${result.id}`)
    },
})

const AeoPromptsImportSchema = () => {
    const AeoPromptsBulkImportBody = orvalSchemas.AeoPromptsBulkImportBody()
    return AeoPromptsBulkImportBody
}

const aeoPromptsImport = (): ToolBase<ReturnType<typeof AeoPromptsImportSchema>, Schemas.AEOPromptImportResult> => ({
    name: 'aeo-prompts-import',
    schema: AeoPromptsImportSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof AeoPromptsImportSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.prompts !== undefined) {
            body['prompts'] = params.prompts
        }
        const result = await context.api.request<Schemas.AEOPromptImportResult>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/aeo_prompts/bulk_import/`,
            body,
        })
        return result
    },
})

const AeoPromptsListSchema = () => {
    const AeoPromptsListQueryParams = orvalSchemas.AeoPromptsListQueryParams()
    return AeoPromptsListQueryParams
}

const aeoPromptsList = (): ToolBase<
    ReturnType<typeof AeoPromptsListSchema>,
    WithPostHogUrl<Schemas.PaginatedAEOPromptList>
> => ({
    name: 'aeo-prompts-list',
    schema: AeoPromptsListSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof AeoPromptsListSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.PaginatedAEOPromptList>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/aeo_prompts/`,
            query: {
                active: params.active,
                branded: params.branded,
                include_archived: params.include_archived,
                limit: params.limit,
                needs_improvement: params.needs_improvement,
                offset: params.offset,
                topic: params.topic,
            },
        })
        return await withPostHogUrl(
            context,
            {
                ...result,
                results: await Promise.all(
                    (result.results ?? []).map((item) =>
                        withPostHogUrl(context, item, `/web/ai-visibility/prompts/${item.id}`)
                    )
                ),
            },
            '/web/ai-visibility'
        )
    },
})

const AeoPromptsOverviewGetSchema = () => {
    const AeoPromptsOverviewQueryParams = orvalSchemas.AeoPromptsOverviewQueryParams()
    return AeoPromptsOverviewQueryParams
}

const aeoPromptsOverviewGet = (): ToolBase<
    ReturnType<typeof AeoPromptsOverviewGetSchema>,
    Schemas.AEOPromptSetOverview
> => ({
    name: 'aeo-prompts-overview-get',
    schema: AeoPromptsOverviewGetSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof AeoPromptsOverviewGetSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.AEOPromptSetOverview>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/aeo_prompts/overview/`,
            query: {
                branded: params.branded,
                days: params.days,
            },
        })
        return result
    },
})

const AeoPromptsRankingsGetSchema = () => {
    const AeoPromptsRankingsQueryParams = orvalSchemas.AeoPromptsRankingsQueryParams()
    return AeoPromptsRankingsQueryParams
}

const aeoPromptsRankingsGet = (): ToolBase<
    ReturnType<typeof AeoPromptsRankingsGetSchema>,
    Schemas.AEOPromptSetRankings
> => ({
    name: 'aeo-prompts-rankings-get',
    schema: AeoPromptsRankingsGetSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof AeoPromptsRankingsGetSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.AEOPromptSetRankings>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/aeo_prompts/rankings/`,
            query: {
                branded: params.branded,
                days: params.days,
            },
        })
        return result
    },
})

const AeoPromptsStatsGetSchema = () => {
    const AeoPromptsStatsParams = orvalSchemas.AeoPromptsStatsParams()
    return AeoPromptsStatsParams.omit({ project_id: true }).extend({
        id: AeoPromptsStatsParams.shape['id'].describe('The prompt id (a UUID), from `aeo-prompts-list`.'),
    })
}

const aeoPromptsStatsGet = (): ToolBase<
    ReturnType<typeof AeoPromptsStatsGetSchema>,
    WithPostHogUrl<Schemas.AEOPromptStats>
> => ({
    name: 'aeo-prompts-stats-get',
    schema: AeoPromptsStatsGetSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof AeoPromptsStatsGetSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.AEOPromptStats>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/aeo_prompts/${encodeURIComponent(String(params.id))}/stats/`,
        })
        return await withPostHogUrl(context, result, `/web/ai-visibility/prompts/${params.id}`)
    },
})

const AeoPromptsSuggestSchema = () => {
    const AeoPromptsSuggestBody = orvalSchemas.AeoPromptsSuggestBody()
    return AeoPromptsSuggestBody
}

const aeoPromptsSuggest = (): ToolBase<ReturnType<typeof AeoPromptsSuggestSchema>, unknown> => ({
    name: 'aeo-prompts-suggest',
    schema: AeoPromptsSuggestSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof AeoPromptsSuggestSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.domain !== undefined) {
            body['domain'] = params.domain
        }
        if (params.brand !== undefined) {
            body['brand'] = params.brand
        }
        if (params.description !== undefined) {
            body['description'] = params.description
        }
        if (params.competitors !== undefined) {
            body['competitors'] = params.competitors
        }
        if (params.topics !== undefined) {
            body['topics'] = params.topics
        }
        if (params.count !== undefined) {
            body['count'] = params.count
        }
        const result = await context.api.request<unknown>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/aeo_prompts/suggest/`,
            body,
        })
        return result
    },
})

const AeoPromptsSuggestionGetSchema = () => {
    const AeoPromptsSuggestionRetrieveParams = orvalSchemas.AeoPromptsSuggestionRetrieveParams()
    return AeoPromptsSuggestionRetrieveParams.omit({ project_id: true })
}

const aeoPromptsSuggestionGet = (): ToolBase<
    ReturnType<typeof AeoPromptsSuggestionGetSchema>,
    Schemas.AEOPromptSuggestionJob
> => ({
    name: 'aeo-prompts-suggestion-get',
    schema: AeoPromptsSuggestionGetSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof AeoPromptsSuggestionGetSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.AEOPromptSuggestionJob>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/aeo_prompts/suggest/${encodeURIComponent(String(params.job_id))}/`,
        })
        return result
    },
})

const AeoPromptsTopicsListSchema = () => z.object({})

const aeoPromptsTopicsList = (): ToolBase<ReturnType<typeof AeoPromptsTopicsListSchema>, Schemas.AEOPromptTopic[]> => ({
    name: 'aeo-prompts-topics-list',
    schema: AeoPromptsTopicsListSchema(),
    handler: async (context: Context, _params: z.infer<ReturnType<typeof AeoPromptsTopicsListSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.AEOPromptTopic[]>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/aeo_prompts/topics/`,
        })
        return result
    },
})

const AeoPromptsUpdateSchema = () => {
    const AeoPromptsPartialUpdateBody = orvalSchemas.AeoPromptsPartialUpdateBody()
    const AeoPromptsPartialUpdateParams = orvalSchemas.AeoPromptsPartialUpdateParams()
    return AeoPromptsPartialUpdateParams.omit({ project_id: true })
        .extend(AeoPromptsPartialUpdateBody.shape)
        .extend({
            id: AeoPromptsPartialUpdateParams.shape['id'].describe('The prompt id (a UUID), from `aeo-prompts-list`.'),
        })
}

const aeoPromptsUpdate = (): ToolBase<
    ReturnType<typeof AeoPromptsUpdateSchema>,
    WithPostHogUrl<Schemas.AEOPrompt>
> => ({
    name: 'aeo-prompts-update',
    schema: AeoPromptsUpdateSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof AeoPromptsUpdateSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.active !== undefined) {
            body['active'] = params.active
        }
        if (params.topic !== undefined) {
            body['topic'] = params.topic
        }
        if (params.prompt !== undefined) {
            body['prompt'] = params.prompt
        }
        if (params.version_description !== undefined) {
            body['version_description'] = params.version_description
        }
        if (params.current_version !== undefined) {
            body['current_version'] = params.current_version
        }
        if (params.archived !== undefined) {
            body['archived'] = params.archived
        }
        const result = await context.api.request<Schemas.AEOPrompt>({
            method: 'PATCH',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/aeo_prompts/${encodeURIComponent(String(params.id))}/`,
            body,
        })
        return await withPostHogUrl(context, result, `/web/ai-visibility/prompts/${result.id}`)
    },
})

const AeoPromptsVersionsListSchema = () => {
    const AeoPromptsVersionsParams = orvalSchemas.AeoPromptsVersionsParams()
    return AeoPromptsVersionsParams.omit({ project_id: true }).extend({
        id: AeoPromptsVersionsParams.shape['id'].describe('The prompt id (a UUID), from `aeo-prompts-list`.'),
    })
}

const aeoPromptsVersionsList = (): ToolBase<
    ReturnType<typeof AeoPromptsVersionsListSchema>,
    Schemas.AEOPromptVersion[]
> => ({
    name: 'aeo-prompts-versions-list',
    schema: AeoPromptsVersionsListSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof AeoPromptsVersionsListSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.AEOPromptVersion[]>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/aeo_prompts/${encodeURIComponent(String(params.id))}/versions/`,
        })
        return result
    },
})

const AeoSetupContextGetSchema = () => z.object({})

const aeoSetupContextGet = (): ToolBase<ReturnType<typeof AeoSetupContextGetSchema>, Schemas.AEOSetupContext> => ({
    name: 'aeo-setup-context-get',
    schema: AeoSetupContextGetSchema(),
    handler: async (context: Context, _params: z.infer<ReturnType<typeof AeoSetupContextGetSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.AEOSetupContext>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/aeo_setup/context/`,
        })
        return result
    },
})

const AeoSetupGetSchema = () => {
    const AeoSetupRetrieveParams = orvalSchemas.AeoSetupRetrieveParams()
    return AeoSetupRetrieveParams.omit({ project_id: true }).extend({
        id: AeoSetupRetrieveParams.shape['id'].describe('The setup job id, from `aeo-setup-start`.'),
    })
}

const aeoSetupGet = (): ToolBase<ReturnType<typeof AeoSetupGetSchema>, Schemas.AEOSetupJob> => ({
    name: 'aeo-setup-get',
    schema: AeoSetupGetSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof AeoSetupGetSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.AEOSetupJob>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/aeo_setup/${encodeURIComponent(String(params.id))}/`,
        })
        return result
    },
})

const AeoSetupStartSchema = () => {
    const AeoSetupCreateBody = orvalSchemas.AeoSetupCreateBody()
    return AeoSetupCreateBody
}

const aeoSetupStart = (): ToolBase<ReturnType<typeof AeoSetupStartSchema>, unknown> => ({
    name: 'aeo-setup-start',
    schema: AeoSetupStartSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof AeoSetupStartSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.domain !== undefined) {
            body['domain'] = params.domain
        }
        if (params.brand !== undefined) {
            body['brand'] = params.brand
        }
        if (params.description !== undefined) {
            body['description'] = params.description
        }
        if (params.engines !== undefined) {
            body['engines'] = params.engines
        }
        if (params.run_first_check !== undefined) {
            body['run_first_check'] = params.run_first_check
        }
        if (params.only_first_run !== undefined) {
            body['only_first_run'] = params.only_first_run
        }
        if (params.activate_paused_prompts !== undefined) {
            body['activate_paused_prompts'] = params.activate_paused_prompts
        }
        const result = await context.api.request<unknown>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/aeo_setup/`,
            body,
        })
        return result
    },
})

export const GENERATED_TOOLS: Record<string, () => ToolBase<ZodObjectAny>> = {
    'aeo-brands-create': aeoBrandsCreate,
    'aeo-brands-get': aeoBrandsGet,
    'aeo-brands-list': aeoBrandsList,
    'aeo-brands-update': aeoBrandsUpdate,
    'aeo-engines-list': aeoEnginesList,
    'aeo-engines-update': aeoEnginesUpdate,
    'aeo-keywords-create': aeoKeywordsCreate,
    'aeo-keywords-delete': aeoKeywordsDelete,
    'aeo-keywords-get': aeoKeywordsGet,
    'aeo-keywords-list': aeoKeywordsList,
    'aeo-keywords-modifiers-get': aeoKeywordsModifiersGet,
    'aeo-keywords-report-get': aeoKeywordsReportGet,
    'aeo-keywords-suggest': aeoKeywordsSuggest,
    'aeo-keywords-suggestion-get': aeoKeywordsSuggestionGet,
    'aeo-prompts-archive': aeoPromptsArchive,
    'aeo-prompts-checks-list': aeoPromptsChecksList,
    'aeo-prompts-create-dashboard': aeoPromptsCreateDashboard,
    'aeo-prompts-get': aeoPromptsGet,
    'aeo-prompts-import': aeoPromptsImport,
    'aeo-prompts-list': aeoPromptsList,
    'aeo-prompts-overview-get': aeoPromptsOverviewGet,
    'aeo-prompts-rankings-get': aeoPromptsRankingsGet,
    'aeo-prompts-stats-get': aeoPromptsStatsGet,
    'aeo-prompts-suggest': aeoPromptsSuggest,
    'aeo-prompts-suggestion-get': aeoPromptsSuggestionGet,
    'aeo-prompts-topics-list': aeoPromptsTopicsList,
    'aeo-prompts-update': aeoPromptsUpdate,
    'aeo-prompts-versions-list': aeoPromptsVersionsList,
    'aeo-setup-context-get': aeoSetupContextGet,
    'aeo-setup-get': aeoSetupGet,
    'aeo-setup-start': aeoSetupStart,
}
