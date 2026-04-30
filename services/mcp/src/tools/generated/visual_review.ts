// AUTO-GENERATED from products/visual_review/mcp/tools.yaml + OpenAPI — do not edit
import { z } from 'zod'

import type { Schemas } from '@/api/generated'
import {
    VisualReviewReposListQueryParams,
    VisualReviewReposRetrieveParams,
    VisualReviewRunsListQueryParams,
    VisualReviewRunsRetrieveParams,
    VisualReviewRunsSnapshotHistoryListParams,
    VisualReviewRunsSnapshotHistoryListQueryParams,
    VisualReviewRunsSnapshotsListParams,
    VisualReviewRunsSnapshotsListQueryParams,
    VisualReviewRunsToleratedHashesListParams,
    VisualReviewRunsToleratedHashesListQueryParams,
} from '@/generated/visual_review/api'
import { withPostHogUrl, type WithPostHogUrl } from '@/tools/tool-utils'
import type { Context, ToolBase, ZodObjectAny } from '@/tools/types'

const VisualReviewReposListSchema = VisualReviewReposListQueryParams

const visualReviewReposList = (): ToolBase<
    typeof VisualReviewReposListSchema,
    WithPostHogUrl<Schemas.PaginatedRepoList>
> => ({
    name: 'visual-review-repos-list',
    schema: VisualReviewReposListSchema,
    handler: async (context: Context, params: z.infer<typeof VisualReviewReposListSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.PaginatedRepoList>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/visual_review/repos/`,
            query: {
                limit: params.limit,
                offset: params.offset,
            },
        })
        return await withPostHogUrl(context, result, '/visual_review')
    },
})

const VisualReviewReposRetrieveSchema = VisualReviewReposRetrieveParams.omit({ project_id: true })

const visualReviewReposRetrieve = (): ToolBase<typeof VisualReviewReposRetrieveSchema, Schemas.Repo> => ({
    name: 'visual-review-repos-retrieve',
    schema: VisualReviewReposRetrieveSchema,
    handler: async (context: Context, params: z.infer<typeof VisualReviewReposRetrieveSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.Repo>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/visual_review/repos/${encodeURIComponent(String(params.id))}/`,
        })
        return result
    },
})

const VisualReviewRunsCountsRetrieveSchema = z.object({})

const visualReviewRunsCountsRetrieve = (): ToolBase<
    typeof VisualReviewRunsCountsRetrieveSchema,
    Schemas.ReviewStateCounts
> => ({
    name: 'visual-review-runs-counts-retrieve',
    schema: VisualReviewRunsCountsRetrieveSchema,
    // eslint-disable-next-line no-unused-vars
    handler: async (context: Context, params: z.infer<typeof VisualReviewRunsCountsRetrieveSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.ReviewStateCounts>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/visual_review/runs/counts/`,
        })
        return result
    },
})

const VisualReviewRunsListSchema = VisualReviewRunsListQueryParams

const visualReviewRunsList = (): ToolBase<
    typeof VisualReviewRunsListSchema,
    WithPostHogUrl<Schemas.PaginatedRunList>
> => ({
    name: 'visual-review-runs-list',
    schema: VisualReviewRunsListSchema,
    handler: async (context: Context, params: z.infer<typeof VisualReviewRunsListSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.PaginatedRunList>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/visual_review/runs/`,
            query: {
                branch: params.branch,
                commit_sha: params.commit_sha,
                limit: params.limit,
                offset: params.offset,
                pr_number: params.pr_number,
                review_state: params.review_state,
            },
        })
        return await withPostHogUrl(
            context,
            {
                ...result,
                results: await Promise.all(
                    (result.results ?? []).map((item) =>
                        withPostHogUrl(context, item, `/visual_review/runs/${item.id}`)
                    )
                ),
            },
            '/visual_review'
        )
    },
})

const VisualReviewRunsRetrieveSchema = VisualReviewRunsRetrieveParams.omit({ project_id: true })

const visualReviewRunsRetrieve = (): ToolBase<typeof VisualReviewRunsRetrieveSchema, WithPostHogUrl<Schemas.Run>> => ({
    name: 'visual-review-runs-retrieve',
    schema: VisualReviewRunsRetrieveSchema,
    handler: async (context: Context, params: z.infer<typeof VisualReviewRunsRetrieveSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.Run>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/visual_review/runs/${encodeURIComponent(String(params.id))}/`,
        })
        return await withPostHogUrl(context, result, `/visual_review/runs/${result.id}`)
    },
})

const VisualReviewRunsSnapshotHistoryListSchema = VisualReviewRunsSnapshotHistoryListParams.omit({
    project_id: true,
}).extend(VisualReviewRunsSnapshotHistoryListQueryParams.shape)

const visualReviewRunsSnapshotHistoryList = (): ToolBase<
    typeof VisualReviewRunsSnapshotHistoryListSchema,
    Schemas.PaginatedSnapshotHistoryEntryList
> => ({
    name: 'visual-review-runs-snapshot-history-list',
    schema: VisualReviewRunsSnapshotHistoryListSchema,
    handler: async (context: Context, params: z.infer<typeof VisualReviewRunsSnapshotHistoryListSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.PaginatedSnapshotHistoryEntryList>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/visual_review/runs/${encodeURIComponent(String(params.id))}/snapshot-history/`,
            query: {
                identifier: params.identifier,
                limit: params.limit,
                offset: params.offset,
            },
        })
        return result
    },
})

const VisualReviewRunsSnapshotsListSchema = VisualReviewRunsSnapshotsListParams.omit({ project_id: true }).extend(
    VisualReviewRunsSnapshotsListQueryParams.shape
)

const visualReviewRunsSnapshotsList = (): ToolBase<
    typeof VisualReviewRunsSnapshotsListSchema,
    WithPostHogUrl<Schemas.PaginatedSnapshotList>
> => ({
    name: 'visual-review-runs-snapshots-list',
    schema: VisualReviewRunsSnapshotsListSchema,
    handler: async (context: Context, params: z.infer<typeof VisualReviewRunsSnapshotsListSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.PaginatedSnapshotList>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/visual_review/runs/${encodeURIComponent(String(params.id))}/snapshots/`,
            query: {
                limit: params.limit,
                offset: params.offset,
            },
        })
        return await withPostHogUrl(context, result, '/visual_review')
    },
})

const VisualReviewRunsToleratedHashesListSchema = VisualReviewRunsToleratedHashesListParams.omit({
    project_id: true,
}).extend(VisualReviewRunsToleratedHashesListQueryParams.shape)

const visualReviewRunsToleratedHashesList = (): ToolBase<
    typeof VisualReviewRunsToleratedHashesListSchema,
    Schemas.PaginatedToleratedHashEntryList
> => ({
    name: 'visual-review-runs-tolerated-hashes-list',
    schema: VisualReviewRunsToleratedHashesListSchema,
    handler: async (context: Context, params: z.infer<typeof VisualReviewRunsToleratedHashesListSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.PaginatedToleratedHashEntryList>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/visual_review/runs/${encodeURIComponent(String(params.id))}/tolerated-hashes/`,
            query: {
                identifier: params.identifier,
                limit: params.limit,
                offset: params.offset,
            },
        })
        return result
    },
})

export const GENERATED_TOOLS: Record<string, () => ToolBase<ZodObjectAny>> = {
    'visual-review-repos-list': visualReviewReposList,
    'visual-review-repos-retrieve': visualReviewReposRetrieve,
    'visual-review-runs-counts-retrieve': visualReviewRunsCountsRetrieve,
    'visual-review-runs-list': visualReviewRunsList,
    'visual-review-runs-retrieve': visualReviewRunsRetrieve,
    'visual-review-runs-snapshot-history-list': visualReviewRunsSnapshotHistoryList,
    'visual-review-runs-snapshots-list': visualReviewRunsSnapshotsList,
    'visual-review-runs-tolerated-hashes-list': visualReviewRunsToleratedHashesList,
}
