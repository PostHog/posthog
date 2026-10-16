/**
 * Hooks for the generated `update-feature-flag` tool. They intercept only `filters`: the
 * request hook preserves group targeting (PostHog/posthog#46501) and the response hook
 * reports how the release conditions changed. Everything else is left to the generated
 * handler. Re-sync is needed only if the `filters` param shape changes.
 */
import type { Schemas } from '@/api/generated'
import type { ToolHooks } from '@/tools/tool-hooks'
import type { Context } from '@/tools/types'

import { describeFiltersChange } from './describeFiltersChange'
import { preserveGroupTargetingFilters, type FlagFilters } from './preserveGroupTargeting'

type UpdateParams = {
    id: number | string
    filters?: FlagFilters | null
    _previousFilters?: FlagFilters
    [key: string]: unknown
}

async function beforeRequest<T extends UpdateParams>(context: Context, params: T): Promise<T> {
    if (params.filters === undefined) {
        return params
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

    return { ...params, filters: mergedFilters, _previousFilters: existingFilters ?? {} }
}

function afterResponse(_context: Context, params: UpdateParams, result: unknown): unknown {
    if (params._previousFilters === undefined) {
        return result
    }
    const updated = result as { filters?: unknown } | null | undefined
    const filters = updated?.filters
    if (!filters || typeof filters !== 'object' || Array.isArray(filters)) {
        return result
    }
    return { ...updated, filters_change: describeFiltersChange(params._previousFilters, filters as FlagFilters) }
}

export default { beforeRequest, afterResponse } satisfies ToolHooks<UpdateParams>
