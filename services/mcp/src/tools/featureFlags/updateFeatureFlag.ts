/**
 * Hand-written override of generated `update-feature-flag`. It intercepts only
 * `filters`, to preserve group targeting (PostHog/posthog#46501), and delegates
 * everything else to the codegen factory. Re-sync is needed only if the generated
 * tool name or the `filters` param shape changes.
 *
 * Title, description, and scopes still resolve from the generated
 * `update-feature-flag` entry, not from this file.
 */
import type { Schemas } from '@/api/generated'
import { GENERATED_TOOLS } from '@/tools/generated/feature_flags'
import type { Context, ToolBase, ZodObjectAny } from '@/tools/types'

import { preserveGroupTargetingFilters, type FlagFilters } from './preserveGroupTargeting'

type UpdateParams = {
    id: number | string
    filters?: FlagFilters
    [key: string]: unknown
}

export default function updateFeatureFlagPreservingGroups(): ToolBase<ZodObjectAny> {
    const generated = GENERATED_TOOLS['update-feature-flag']!()

    return {
        // Spreading the generated tool carries over any field codegen adds later.
        ...generated,
        handler: async (context: Context, params: UpdateParams) => {
            if (params.filters === undefined) {
                return generated.handler(context, params)
            }

            // No try/catch: a failed GET must abort before the PATCH. PATCHing raw
            // filters without the merge is what silently demotes group flags.
            const projectId = await context.stateManager.getProjectId()
            const existing = await context.api.request<Schemas.FeatureFlag>({
                method: 'GET',
                path: `/api/projects/${encodeURIComponent(String(projectId))}/feature_flags/${encodeURIComponent(String(params.id))}/`,
            })
            const existingFilters = (existing?.filters ?? undefined) as FlagFilters | undefined
            const mergedFilters = preserveGroupTargetingFilters(existingFilters, params.filters)

            return generated.handler(context, { ...params, filters: mergedFilters })
        },
    }
}
