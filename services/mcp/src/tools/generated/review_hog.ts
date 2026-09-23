// AUTO-GENERATED from products/review_hog/mcp/tools.yaml + OpenAPI — do not edit
import { z } from 'zod'

import type { Schemas } from '@/api/generated'
import * as orvalSchemas from '@/generated/review_hog/api'
import { withPostHogUrl, type WithPostHogUrl } from '@/tools/tool-utils'
import type { Context, ToolBase, ZodObjectAny } from '@/tools/types'

const ReviewHogReviewsGetSchema = () => {
    const ReviewHogReviewsRetrieveParams = orvalSchemas.ReviewHogReviewsRetrieveParams()
    return ReviewHogReviewsRetrieveParams.omit({ project_id: true })
}

const reviewHogReviewsGet = (): ToolBase<ReturnType<typeof ReviewHogReviewsGetSchema>, Schemas.ReviewDetail> => ({
    name: 'review-hog-reviews-get',
    schema: ReviewHogReviewsGetSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof ReviewHogReviewsGetSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.ReviewDetail>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/review_hog/reviews/${encodeURIComponent(String(params.id))}/`,
        })
        return result
    },
})

const ReviewHogReviewsListSchema = () => {
    const ReviewHogReviewsListQueryParams = orvalSchemas.ReviewHogReviewsListQueryParams()
    return ReviewHogReviewsListQueryParams
}

const reviewHogReviewsList = (): ToolBase<
    ReturnType<typeof ReviewHogReviewsListSchema>,
    WithPostHogUrl<Schemas.ReviewRecentReviewsPage>
> => ({
    name: 'review-hog-reviews-list',
    schema: ReviewHogReviewsListSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof ReviewHogReviewsListSchema>>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.ReviewRecentReviewsPage>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/review_hog/reviews/`,
            query: {
                limit: params.limit,
                scope: params.scope,
            },
        })
        return await withPostHogUrl(context, result, '/code-review')
    },
})

const ReviewHogReviewsTriggerSchema = () => {
    const ReviewHogReviewsTriggerCreateBody = orvalSchemas.ReviewHogReviewsTriggerCreateBody()
    return ReviewHogReviewsTriggerCreateBody
}

const reviewHogReviewsTrigger = (): ToolBase<
    ReturnType<typeof ReviewHogReviewsTriggerSchema>,
    Schemas.ReviewTriggerResponse
> => ({
    name: 'review-hog-reviews-trigger',
    schema: ReviewHogReviewsTriggerSchema(),
    handler: async (context: Context, params: z.infer<ReturnType<typeof ReviewHogReviewsTriggerSchema>>) => {
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
            path: `/api/projects/${encodeURIComponent(String(projectId))}/review_hog/reviews/trigger/`,
            body,
        })
        return result
    },
})

export const GENERATED_TOOLS: Record<string, () => ToolBase<ZodObjectAny>> = {
    'review-hog-reviews-get': reviewHogReviewsGet,
    'review-hog-reviews-list': reviewHogReviewsList,
    'review-hog-reviews-trigger': reviewHogReviewsTrigger,
}
