// AUTO-GENERATED from products/review_hog/mcp/tools.yaml + OpenAPI — do not edit
import { z } from 'zod'

import type { Schemas } from '@/api/generated'
import {
    ReviewHogReviewsListQueryParams,
    ReviewHogReviewsRetrieveParams,
    ReviewHogReviewsTriggerCreateBody,
} from '@/generated/review_hog/api'
import { withPostHogUrl, type WithPostHogUrl } from '@/tools/tool-utils'
import type { Context, ToolBase, ZodObjectAny } from '@/tools/types'

const ReviewHogReviewsGetSchema = ReviewHogReviewsRetrieveParams.omit({ project_id: true })

const reviewHogReviewsGet = (): ToolBase<typeof ReviewHogReviewsGetSchema, Schemas.ReviewDetail> => ({
    name: 'review-hog-reviews-get',
    schema: ReviewHogReviewsGetSchema,
    handler: async (context: Context, params: z.infer<typeof ReviewHogReviewsGetSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.ReviewDetail>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/review_hog/reviews/${encodeURIComponent(String(params.id))}/`,
        })
        return result
    },
})

const ReviewHogReviewsListSchema = ReviewHogReviewsListQueryParams

const reviewHogReviewsList = (): ToolBase<
    typeof ReviewHogReviewsListSchema,
    WithPostHogUrl<Schemas.ReviewRecentReviewsPage>
> => ({
    name: 'review-hog-reviews-list',
    schema: ReviewHogReviewsListSchema,
    handler: async (context: Context, params: z.infer<typeof ReviewHogReviewsListSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.ReviewRecentReviewsPage>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/review_hog/reviews/`,
            query: {
                limit: params.limit,
                scope: params.scope,
            },
        })
        return await withPostHogUrl(context, result, '/code_review')
    },
})

const ReviewHogReviewsTriggerSchema = ReviewHogReviewsTriggerCreateBody

const reviewHogReviewsTrigger = (): ToolBase<typeof ReviewHogReviewsTriggerSchema, Schemas.ReviewTriggerResponse> => ({
    name: 'review-hog-reviews-trigger',
    schema: ReviewHogReviewsTriggerSchema,
    handler: async (context: Context, params: z.infer<typeof ReviewHogReviewsTriggerSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.pr_url !== undefined) {
            body['pr_url'] = params.pr_url
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
