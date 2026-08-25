// AUTO-GENERATED from products/stamphog/mcp/tools.yaml + OpenAPI — do not edit
import { z } from 'zod'

import type { Schemas } from '@/api/generated'
import {
    StamphogDigestRunsListQueryParams,
    StamphogPullRequestsListQueryParams,
    StamphogPullRequestsRetrieveParams,
    StamphogRepoConfigsDestroyParams,
    StamphogRepoConfigsListQueryParams,
    StamphogRepoConfigsRetrieveParams,
    StamphogReviewRunsListQueryParams,
    StamphogReviewRunsRetrieveParams,
} from '@/generated/stamphog/api'
import { withPostHogUrl, omitResponseFields, type WithPostHogUrl } from '@/tools/tool-utils'
import type { Context, ToolBase, ZodObjectAny } from '@/tools/types'

const StamphogDigestRunsListSchema = StamphogDigestRunsListQueryParams

const stamphogDigestRunsList = (): ToolBase<
    typeof StamphogDigestRunsListSchema,
    WithPostHogUrl<Schemas.PaginatedDigestRunList>
> => ({
    name: 'stamphog-digest-runs-list',
    schema: StamphogDigestRunsListSchema,
    handler: async (context: Context, params: z.infer<typeof StamphogDigestRunsListSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.PaginatedDigestRunList>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/stamphog/digest_runs/`,
            query: {
                limit: params.limit,
                offset: params.offset,
                slack_channel_id: params.slack_channel_id,
            },
        })
        return await withPostHogUrl(context, result, '/stamphog')
    },
})

const StamphogPullRequestsGetSchema = StamphogPullRequestsRetrieveParams.omit({ project_id: true })

const stamphogPullRequestsGet = (): ToolBase<typeof StamphogPullRequestsGetSchema, Schemas.StamphogPullRequest> => ({
    name: 'stamphog-pull-requests-get',
    schema: StamphogPullRequestsGetSchema,
    handler: async (context: Context, params: z.infer<typeof StamphogPullRequestsGetSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.StamphogPullRequest>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/stamphog/pull_requests/${encodeURIComponent(String(params.id))}/`,
        })
        return result
    },
})

const StamphogPullRequestsListSchema = StamphogPullRequestsListQueryParams

const stamphogPullRequestsList = (): ToolBase<
    typeof StamphogPullRequestsListSchema,
    WithPostHogUrl<Schemas.PaginatedStamphogPullRequestList>
> => ({
    name: 'stamphog-pull-requests-list',
    schema: StamphogPullRequestsListSchema,
    handler: async (context: Context, params: z.infer<typeof StamphogPullRequestsListSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.PaginatedStamphogPullRequestList>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/stamphog/pull_requests/`,
            query: {
                limit: params.limit,
                merged: params.merged,
                offset: params.offset,
                pr_number: params.pr_number,
            },
        })
        return await withPostHogUrl(context, result, '/stamphog')
    },
})

const StamphogRepoConfigsDeleteSchema = StamphogRepoConfigsDestroyParams.omit({ project_id: true })

const stamphogRepoConfigsDelete = (): ToolBase<typeof StamphogRepoConfigsDeleteSchema, unknown> => ({
    name: 'stamphog-repo-configs-delete',
    schema: StamphogRepoConfigsDeleteSchema,
    handler: async (context: Context, params: z.infer<typeof StamphogRepoConfigsDeleteSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<unknown>({
            method: 'DELETE',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/stamphog/repo_configs/${encodeURIComponent(String(params.id))}/`,
        })
        return result
    },
})

const StamphogRepoConfigsGetSchema = StamphogRepoConfigsRetrieveParams.omit({ project_id: true })

const stamphogRepoConfigsGet = (): ToolBase<typeof StamphogRepoConfigsGetSchema, Schemas.StamphogRepoConfig> => ({
    name: 'stamphog-repo-configs-get',
    schema: StamphogRepoConfigsGetSchema,
    handler: async (context: Context, params: z.infer<typeof StamphogRepoConfigsGetSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.StamphogRepoConfig>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/stamphog/repo_configs/${encodeURIComponent(String(params.id))}/`,
        })
        return result
    },
})

const StamphogRepoConfigsListSchema = StamphogRepoConfigsListQueryParams

const stamphogRepoConfigsList = (): ToolBase<
    typeof StamphogRepoConfigsListSchema,
    WithPostHogUrl<Schemas.PaginatedStamphogRepoConfigList>
> => ({
    name: 'stamphog-repo-configs-list',
    schema: StamphogRepoConfigsListSchema,
    handler: async (context: Context, params: z.infer<typeof StamphogRepoConfigsListSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.PaginatedStamphogRepoConfigList>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/stamphog/repo_configs/`,
            query: {
                limit: params.limit,
                offset: params.offset,
            },
        })
        return await withPostHogUrl(context, result, '/stamphog')
    },
})

const StamphogReviewRunsGetSchema = StamphogReviewRunsRetrieveParams.omit({ project_id: true })

const stamphogReviewRunsGet = (): ToolBase<typeof StamphogReviewRunsGetSchema, Schemas.ReviewRun> => ({
    name: 'stamphog-review-runs-get',
    schema: StamphogReviewRunsGetSchema,
    handler: async (context: Context, params: z.infer<typeof StamphogReviewRunsGetSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.ReviewRun>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/stamphog/review_runs/${encodeURIComponent(String(params.id))}/`,
        })
        return result
    },
})

const StamphogReviewRunsListSchema = StamphogReviewRunsListQueryParams

const stamphogReviewRunsList = (): ToolBase<
    typeof StamphogReviewRunsListSchema,
    WithPostHogUrl<Schemas.PaginatedReviewRunList>
> => ({
    name: 'stamphog-review-runs-list',
    schema: StamphogReviewRunsListSchema,
    handler: async (context: Context, params: z.infer<typeof StamphogReviewRunsListSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.PaginatedReviewRunList>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/stamphog/review_runs/`,
            query: {
                limit: params.limit,
                offset: params.offset,
                pr_number: params.pr_number,
                repository: params.repository,
                status: params.status,
                trigger: params.trigger,
            },
        })
        const filtered = {
            ...result,
            results: (result.results ?? []).map((item: any) => omitResponseFields(item, ['output'])),
        } as typeof result
        return await withPostHogUrl(context, filtered, '/stamphog')
    },
})

export const GENERATED_TOOLS: Record<string, () => ToolBase<ZodObjectAny>> = {
    'stamphog-digest-runs-list': stamphogDigestRunsList,
    'stamphog-pull-requests-get': stamphogPullRequestsGet,
    'stamphog-pull-requests-list': stamphogPullRequestsList,
    'stamphog-repo-configs-delete': stamphogRepoConfigsDelete,
    'stamphog-repo-configs-get': stamphogRepoConfigsGet,
    'stamphog-repo-configs-list': stamphogRepoConfigsList,
    'stamphog-review-runs-get': stamphogReviewRunsGet,
    'stamphog-review-runs-list': stamphogReviewRunsList,
}
