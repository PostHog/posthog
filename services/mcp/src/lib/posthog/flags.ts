import { getPostHogClient } from './client'

// Group type → group key, matching the `$groups` shape from `buildMCPAnalyticsGroups`.
export type FlagGroups = Record<string, string>

export async function isFeatureFlagEnabled(flagKey: string, distinctId: string, groups?: FlagGroups): Promise<boolean> {
    try {
        const client = getPostHogClient()
        const hasGroups = groups && Object.keys(groups).length > 0
        const result = await client.isFeatureEnabled(flagKey, distinctId, hasGroups ? { groups } : undefined)
        return result === true
    } catch {
        return false
    }
}

<<<<<<< New base: formatting, combine flags call, small fixes
/**
 * Evaluate multiple feature flags in parallel for the given user.
 * Returns a map of flag key → boolean. `groups` is forwarded to posthog-node
 * so group-scoped rollouts (e.g. per-organization) evaluate correctly.
 */
export async function evaluateFeatureFlags(
    flagKeys: string[],
    distinctId: string,
    groups?: FlagGroups
): Promise<Record<string, boolean>> {
||||||| Common ancestor
/**
 * Evaluate multiple feature flags in parallel for the given user.
 * Returns a map of flag key → boolean.
 */
export async function evaluateFeatureFlags(flagKeys: string[], distinctId: string): Promise<Record<string, boolean>> {
=======
export async function evaluateFeatureFlags(flagKeys: string[], distinctId: string): Promise<Record<string, boolean>> {
>>>>>>> Current commit: formatting, combine flags call, small fixes
    if (flagKeys.length === 0) {
        return {}
    }

<<<<<<< New base: formatting, combine flags call, small fixes
    const results = await Promise.all(
        flagKeys.map(async (key) => {
            const enabled = await isFeatureFlagEnabled(key, distinctId, groups)
            return [key, enabled] as const
        })
    )

    return Object.fromEntries(results)
||||||| Common ancestor
    const results = await Promise.all(
        flagKeys.map(async (key) => {
            const enabled = await isFeatureFlagEnabled(key, distinctId)
            return [key, enabled] as const
        })
    )

    return Object.fromEntries(results)
=======
    const client = getPostHogClient()
    const allFlags = await client.getAllFlags(distinctId, { flagKeys })
    const result: Record<string, boolean> = {}
    for (const key of flagKeys) {
        result[key] = allFlags[key] === true
    }
    return result
>>>>>>> Current commit: formatting, combine flags call, small fixes
}
