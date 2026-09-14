import type { Schemas } from '@/api/generated'
import type { Context } from '@/tools/types'

/**
 * Resolve a flag key through the list endpoint's `key` filter, which is a case-insensitive
 * exact match. It can return more than one flag only when two keys differ solely by case, so
 * the exact-case match is preferred when one exists. Misses and ambiguity are returned, not
 * thrown: each caller words them differently (a miss is data for the by-key lookups).
 *
 * The list row is the full flag, so callers can use it directly instead of fetching by id.
 */
export async function resolveFlagsByKey(
    context: Context,
    projectId: string,
    key: string
): Promise<Schemas.FeatureFlag[]> {
    const list = await context.api.request<Schemas.PaginatedFeatureFlagList>({
        method: 'GET',
        path: `/api/projects/${encodeURIComponent(projectId)}/feature_flags/`,
        query: { key, limit: 5 },
    })
    const results = list.results ?? []
    const exact = results.filter((flag) => flag.key === key)
    return exact.length > 0 ? exact : results
}
