// AUTO-GENERATED from products/engineering_analytics/mcp/tools.yaml + OpenAPI — do not edit
import { z } from 'zod'

import type { Schemas } from '@/api/generated'
import { EngineeringAnalyticsPrLifecycleQueryParams } from '@/generated/engineering_analytics/api'
import type { Context, ToolBase, ZodObjectAny } from '@/tools/types'

const PrLifecycleSchema = EngineeringAnalyticsPrLifecycleQueryParams.extend({
    pr_number: EngineeringAnalyticsPrLifecycleQueryParams.shape['pr_number'].describe(
        'Pull request number to inspect.'
    ),
    repo: EngineeringAnalyticsPrLifecycleQueryParams.shape['repo'].describe(
        "Optional 'owner/name' repository to disambiguate when the PR number exists in more than one connected repo."
    ),
})

const prLifecycle = (): ToolBase<typeof PrLifecycleSchema, Schemas.PRLifecycle> => ({
    name: 'pr-lifecycle',
    schema: PrLifecycleSchema,
    handler: async (context: Context, params: z.infer<typeof PrLifecycleSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<Schemas.PRLifecycle>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/engineering_analytics/pr_lifecycle/`,
            query: {
                pr_number: params.pr_number,
                repo: params.repo,
            },
        })
        return result
    },
})

export const GENERATED_TOOLS: Record<string, () => ToolBase<ZodObjectAny>> = {
    'pr-lifecycle': prLifecycle,
}
