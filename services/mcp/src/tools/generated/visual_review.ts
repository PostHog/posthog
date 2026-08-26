// AUTO-GENERATED from products/visual_review/mcp/tools.yaml + OpenAPI — do not edit
import { z } from 'zod'

import type { Schemas } from '@/api/generated'
import {
    VisualReviewReposBaselinesRetrieveParams,
    VisualReviewReposFlakinessRetrieveParams,
    VisualReviewReposListQueryParams,
    VisualReviewReposQuarantineListParams,
    VisualReviewReposQuarantineListQueryParams,
    VisualReviewReposRetrieveParams,
    VisualReviewReposRunsCountsRetrieveParams,
    VisualReviewReposRunsListParams,
    VisualReviewReposRunsListQueryParams,
    VisualReviewRunsApproveCreateBody,
    VisualReviewRunsApproveCreateParams,
    VisualReviewRunsFinalizeCreateBody,
    VisualReviewRunsFinalizeCreateParams,
    VisualReviewRunsListQueryParams,
    VisualReviewRunsRetrieveParams,
    VisualReviewRunsSnapshotHistoryListParams,
    VisualReviewRunsSnapshotHistoryListQueryParams,
    VisualReviewRunsSnapshotsListParams,
    VisualReviewRunsSnapshotsListQueryParams,
    VisualReviewRunsTolerateCreateBody,
    VisualReviewRunsTolerateCreateParams,
    VisualReviewRunsToleratedHashesListParams,
    VisualReviewRunsToleratedHashesListQueryParams,
} from '@/generated/visual_review/api'
import { withUiApp } from '@/resources/ui-apps'
import { withPostHogUrl, type WithPostHogUrl } from '@/tools/tool-utils'
import type { Context, ToolBase, ZodObjectAny } from '@/tools/types'

const VisualReviewReposBaselinesRetrieveSchema = VisualReviewReposBaselinesRetrieveParams.omit({ project_id: true })

const visualReviewReposBaselinesRetrieve = (): ToolBase<
    typeof VisualReviewReposBaselinesRetrieveSchema,
    Schemas.BaselineOverview
> => ({
    name: 'visual-review-repos-baselines-retrieve',
    schema: VisualReviewReposBaselinesRetrieveSchema,
    handler: async (context: Context, params: z.infer<typeof VisualReviewReposBaselinesRetrieveSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.BaselineOverview>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/visual_review/repos/${encodeURIComponent(String(params.id))}/baselines/`,
        })
        return result
    },
})

const VisualReviewReposFlakinessRetrieveSchema = VisualReviewReposFlakinessRetrieveParams.omit({ project_id: true })

const visualReviewReposFlakinessRetrieve = (): ToolBase<
    typeof VisualReviewReposFlakinessRetrieveSchema,
    Schemas.FlakinessOverview
> => ({
    name: 'visual-review-repos-flakiness-retrieve',
    schema: VisualReviewReposFlakinessRetrieveSchema,
    handler: async (context: Context, params: z.infer<typeof VisualReviewReposFlakinessRetrieveSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.FlakinessOverview>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/visual_review/repos/${encodeURIComponent(String(params.id))}/flakiness/`,
        })
        return result
    },
})

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

const VisualReviewReposQuarantineListSchema = VisualReviewReposQuarantineListParams.omit({ project_id: true }).extend(
    VisualReviewReposQuarantineListQueryParams.shape
)

const visualReviewReposQuarantineList = (): ToolBase<
    typeof VisualReviewReposQuarantineListSchema,
    WithPostHogUrl<Schemas.PaginatedQuarantinedIdentifierEntryList>
> => ({
    name: 'visual-review-repos-quarantine-list',
    schema: VisualReviewReposQuarantineListSchema,
    handler: async (context: Context, params: z.infer<typeof VisualReviewReposQuarantineListSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.PaginatedQuarantinedIdentifierEntryList>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/visual_review/repos/${encodeURIComponent(String(params.id))}/quarantine/`,
            query: {
                identifier: params.identifier,
                limit: params.limit,
                offset: params.offset,
                run_type: params.run_type,
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

const VisualReviewReposRunsCountsRetrieveSchema = VisualReviewReposRunsCountsRetrieveParams.omit({ project_id: true })

const visualReviewReposRunsCountsRetrieve = (): ToolBase<
    typeof VisualReviewReposRunsCountsRetrieveSchema,
    Schemas.ReviewStateCounts
> => ({
    name: 'visual-review-repos-runs-counts-retrieve',
    schema: VisualReviewReposRunsCountsRetrieveSchema,
    handler: async (context: Context, params: z.infer<typeof VisualReviewReposRunsCountsRetrieveSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.ReviewStateCounts>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/visual_review/repos/${encodeURIComponent(String(params.repo_id))}/runs/counts/`,
        })
        return result
    },
})

const VisualReviewReposRunsListSchema = VisualReviewReposRunsListParams.omit({ project_id: true }).extend(
    VisualReviewReposRunsListQueryParams.shape
)

const visualReviewReposRunsList = (): ToolBase<
    typeof VisualReviewReposRunsListSchema,
    WithPostHogUrl<Schemas.PaginatedRunList>
> => ({
    name: 'visual-review-repos-runs-list',
    schema: VisualReviewReposRunsListSchema,
    handler: async (context: Context, params: z.infer<typeof VisualReviewReposRunsListSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.PaginatedRunList>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/visual_review/repos/${encodeURIComponent(String(params.repo_id))}/runs/`,
            query: {
                limit: params.limit,
                offset: params.offset,
                review_state: params.review_state,
                search: params.search,
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

const VisualReviewRunsApproveCreateSchema = VisualReviewRunsApproveCreateParams.omit({ project_id: true }).extend(
    VisualReviewRunsApproveCreateBody.shape
)

const visualReviewRunsApproveCreate = (): ToolBase<typeof VisualReviewRunsApproveCreateSchema, Schemas.Run> => ({
    name: 'visual-review-runs-approve-create',
    schema: VisualReviewRunsApproveCreateSchema,
    handler: async (context: Context, params: z.infer<typeof VisualReviewRunsApproveCreateSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.snapshots !== undefined) {
            body['snapshots'] = params.snapshots
        }
        const result = await context.api.request<Schemas.Run>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/visual_review/runs/${encodeURIComponent(String(params.id))}/approve/`,
            body,
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

const VisualReviewRunsFinalizeCreateSchema = VisualReviewRunsFinalizeCreateParams.omit({ project_id: true }).extend(
    VisualReviewRunsFinalizeCreateBody.shape
)

const visualReviewRunsFinalizeCreate = (): ToolBase<
    typeof VisualReviewRunsFinalizeCreateSchema,
    Schemas.FinalizeResult
> => ({
    name: 'visual-review-runs-finalize-create',
    schema: VisualReviewRunsFinalizeCreateSchema,
    handler: async (context: Context, params: z.infer<typeof VisualReviewRunsFinalizeCreateSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.approve_all !== undefined) {
            body['approve_all'] = params.approve_all
        }
        if (params.commit_to_github !== undefined) {
            body['commit_to_github'] = params.commit_to_github
        }
        if (params.add_images_to_comment_on_pr !== undefined) {
            body['add_images_to_comment_on_pr'] = params.add_images_to_comment_on_pr
        }
        const result = await context.api.request<Schemas.FinalizeResult>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/visual_review/runs/${encodeURIComponent(String(params.id))}/finalize/`,
            body,
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
                search: params.search,
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
> =>
    withUiApp('visual-review-snapshots', {
        name: 'visual-review-runs-snapshots-list',
        schema: VisualReviewRunsSnapshotsListSchema,
        handler: async (context: Context, params: z.infer<typeof VisualReviewRunsSnapshotsListSchema>) => {
            const projectId = await context.stateManager.getProjectId()
            const result = await context.api.request<Schemas.PaginatedSnapshotList>({
                method: 'GET',
                path: `/api/projects/${encodeURIComponent(String(projectId))}/visual_review/runs/${encodeURIComponent(String(params.id))}/snapshots/`,
                query: {
                    include_quarantined: params.include_quarantined,
                    limit: params.limit,
                    offset: params.offset,
                },
            })
            return await withPostHogUrl(context, result, '/visual_review')
        },
    })

const VisualReviewRunsTolerateCreateSchema = VisualReviewRunsTolerateCreateParams.omit({ project_id: true }).extend(
    VisualReviewRunsTolerateCreateBody.shape
)

const visualReviewRunsTolerateCreate = (): ToolBase<typeof VisualReviewRunsTolerateCreateSchema, Schemas.Snapshot> => ({
    name: 'visual-review-runs-tolerate-create',
    schema: VisualReviewRunsTolerateCreateSchema,
    handler: async (context: Context, params: z.infer<typeof VisualReviewRunsTolerateCreateSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.snapshot_id !== undefined) {
            body['snapshot_id'] = params.snapshot_id
        }
        const result = await context.api.request<Schemas.Snapshot>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/visual_review/runs/${encodeURIComponent(String(params.id))}/tolerate/`,
            body,
        })
        return result
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
    'visual-review-repos-baselines-retrieve': visualReviewReposBaselinesRetrieve,
    'visual-review-repos-flakiness-retrieve': visualReviewReposFlakinessRetrieve,
    'visual-review-repos-list': visualReviewReposList,
    'visual-review-repos-quarantine-list': visualReviewReposQuarantineList,
    'visual-review-repos-retrieve': visualReviewReposRetrieve,
    'visual-review-repos-runs-counts-retrieve': visualReviewReposRunsCountsRetrieve,
    'visual-review-repos-runs-list': visualReviewReposRunsList,
    'visual-review-runs-approve-create': visualReviewRunsApproveCreate,
    'visual-review-runs-counts-retrieve': visualReviewRunsCountsRetrieve,
    'visual-review-runs-finalize-create': visualReviewRunsFinalizeCreate,
    'visual-review-runs-list': visualReviewRunsList,
    'visual-review-runs-retrieve': visualReviewRunsRetrieve,
    'visual-review-runs-snapshot-history-list': visualReviewRunsSnapshotHistoryList,
    'visual-review-runs-snapshots-list': visualReviewRunsSnapshotsList,
    'visual-review-runs-tolerate-create': visualReviewRunsTolerateCreate,
    'visual-review-runs-tolerated-hashes-list': visualReviewRunsToleratedHashesList,
}
