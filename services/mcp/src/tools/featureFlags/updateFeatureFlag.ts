/**
 * Hand-written override of generated `update-feature-flag`.
 *
 * Delegates to the codegen factory so body fields / schema stay in sync with
 * OpenAPI regeneration; only intercepts `filters` to preserve group targeting
 * (PostHog/posthog#46501).
 *
 * Keep this thin: when codegen adds a body field, this override still forwards
 * it via the generated handler. Re-sync is only needed if the generated tool
 * name or filters param shape changes — see `generated/feature_flags.ts`.
 *
 * MCP title/description/scopes continue to come from the generated
 * tools.yaml → generated-tool-definitions.json entry for `update-feature-flag`
 * (unlike `feature-flag-get-definition-by-key`, which is hand-written-only and
 * therefore has its own schema/tool-definitions.json entry).
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

/**
 * Production override for `update-feature-flag`: GET current flag, merge group
 * targeting into incoming filters, then PATCH via the generated handler.
 */
export default function updateFeatureFlagPreservingGroups(): ToolBase<ZodObjectAny> {
    const generated = GENERATED_TOOLS['update-feature-flag']!()

    return {
        // Spread the generated tool so its name, schema and any field codegen adds later
        // carry over untouched; only the handler is replaced.
        ...generated,
        handler: async (context: Context, params: UpdateParams) => {
            if (params.filters === undefined) {
                return generated.handler(context, params as never)
            }

            // Fail closed on GET errors (401/403/429/5xx): never PATCH raw filters
            // without merge, or group flags can silently demote to person (#46501).
            const projectId = await context.stateManager.getProjectId()
            const existing = await context.api.request<Schemas.FeatureFlag>({
                method: 'GET',
                path: `/api/projects/${encodeURIComponent(String(projectId))}/feature_flags/${encodeURIComponent(String(params.id))}/`,
            })
            const existingFilters = (existing?.filters ?? undefined) as FlagFilters | undefined
            const mergedFilters = preserveGroupTargetingFilters(existingFilters, params.filters)

            return generated.handler(context, { ...params, filters: mergedFilters } as never)
        },
    }
}
