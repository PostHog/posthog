import type { Schemas } from '@/api/generated'
import type { Context } from '@/tools/types'

/**
 * Resolve a flag key through the list endpoint's `key` filter, which is a case-insensitive
 * exact match. It can return more than one flag only when two keys differ solely by case, so
 * the exact-case match is preferred when one exists. Misses and ambiguity are returned, not
 * thrown: each caller words them differently (a miss is data for the by-key lookups).
 *
 * The list hides archived flags unless `archived` is passed, and archiving an experiment
 * archives its flag, so archived flags are searched whenever the active list has no
 * exact-case match. A case-insensitive active match alone must not settle the lookup,
 * because an exact-case archived flag would then lose to a wrong-case active one.
 */
export async function resolveFlagsByKey(
    context: Context,
    projectId: string,
    key: string
): Promise<Schemas.FeatureFlag[]> {
    const list = async (archived: boolean): Promise<Schemas.FeatureFlag[]> => {
        const page = await context.api.request<Schemas.PaginatedFeatureFlagList>({
            method: 'GET',
            path: `/api/projects/${encodeURIComponent(projectId)}/feature_flags/`,
            query: { key, limit: 20, ...(archived && { archived: true }) },
        })
        return page.results ?? []
    }
    const exactCase = (flags: Schemas.FeatureFlag[]): Schemas.FeatureFlag[] => flags.filter((flag) => flag.key === key)

    const active = await list(false)
    const activeExact = exactCase(active)
    if (activeExact.length > 0) {
        return activeExact
    }
    const archived = await list(true)
    const archivedExact = exactCase(archived)
    return archivedExact.length > 0 ? archivedExact : [...active, ...archived]
}
