// AUTO-GENERATED from products/review_hog/mcp/tools.yaml + OpenAPI — do not edit
import { z } from 'zod'

import type { Schemas } from '@/api/generated'
import * as orvalSchemas from '@/generated/review_hog/api'
import { withPostHogUrl, type WithPostHogUrl } from '@/tools/tool-utils'
import type { Context, ToolBase, ZodObjectAny } from '@/tools/types'

const CodeReviewReviewsGetSchema = () => {
    const CodeReviewReviewsRetrieveParams = orvalSchemas.CodeReviewReviewsRetrieveParams()
    const CodeReviewReviewsRetrieveQueryParams = orvalSchemas.CodeReviewReviewsRetrieveQueryParams()
    return CodeReviewReviewsRetrieveParams.omit({ project_id: true }).extend(CodeReviewReviewsRetrieveQueryParams.shape)
}

const codeReviewReviewsGet = (): ToolBase<ReturnType<typeof CodeReviewReviewsGetSchema>, Schemas.ReviewDetail> => ({
    name: 'code-review-reviews-get',
    schema: CodeReviewReviewsGetSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof CodeReviewReviewsGetSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.ReviewDetail>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/code_review/reviews/${encodeURIComponent(String(params.id))}/`,
            query: {
                run_index: params.run_index,
            },
        })
        return result
    },
})

const CodeReviewReviewsListSchema = () => {
    const CodeReviewReviewsListQueryParams = orvalSchemas.CodeReviewReviewsListQueryParams()
    return CodeReviewReviewsListQueryParams
}

const codeReviewReviewsList = (): ToolBase<
    ReturnType<typeof CodeReviewReviewsListSchema>,
    WithPostHogUrl<Schemas.ReviewRecentReviewsPage>
> => ({
    name: 'code-review-reviews-list',
    schema: CodeReviewReviewsListSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof CodeReviewReviewsListSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.ReviewRecentReviewsPage>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/code_review/reviews/`,
            query: {
                limit: params.limit,
                scope: params.scope,
            },
        })
        return await withPostHogUrl(context, result, '/code-review')
    },
})

const CodeReviewReviewsPrStatusSchema = () => {
    const CodeReviewReviewsPrStatusRetrieveQueryParams = orvalSchemas.CodeReviewReviewsPrStatusRetrieveQueryParams()
    return CodeReviewReviewsPrStatusRetrieveQueryParams
}

const codeReviewReviewsPrStatus = (): ToolBase<
    ReturnType<typeof CodeReviewReviewsPrStatusSchema>,
    Schemas.ReviewPRStatus
> => ({
    name: 'code-review-reviews-pr-status',
    schema: CodeReviewReviewsPrStatusSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof CodeReviewReviewsPrStatusSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.ReviewPRStatus>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/code_review/reviews/pr_status/`,
            query: {
                head_sha: params.head_sha,
                pr_url: params.pr_url,
                requested_at: params.requested_at,
                run_mode: params.run_mode,
            },
        })
        return result
    },
})

const CodeReviewReviewsTriggerSchema = () => {
    const CodeReviewReviewsTriggerCreateBody = orvalSchemas.CodeReviewReviewsTriggerCreateBody()
    return CodeReviewReviewsTriggerCreateBody
}

const codeReviewReviewsTrigger = (): ToolBase<
    ReturnType<typeof CodeReviewReviewsTriggerSchema>,
    Schemas.ReviewTriggerResponse
> => ({
    name: 'code-review-reviews-trigger',
    schema: CodeReviewReviewsTriggerSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof CodeReviewReviewsTriggerSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.pr_url !== undefined) {
            body['pr_url'] = params.pr_url
        }
        if (params.run_mode !== undefined) {
            body['run_mode'] = params.run_mode
        }
        const result = await context.api.request<Schemas.ReviewTriggerResponse>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/code_review/reviews/trigger/`,
            body,
        })
        return result
    },
})

export const GENERATED_TOOLS: Record<string, () => ToolBase<ZodObjectAny>> = {
    'code-review-reviews-get': codeReviewReviewsGet,
    'code-review-reviews-list': codeReviewReviewsList,
    'code-review-reviews-pr-status': codeReviewReviewsPrStatus,
    'code-review-reviews-trigger': codeReviewReviewsTrigger,
}
