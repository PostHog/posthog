import { getPostHogClient } from './client'

// Group type → group key, matching the `$groups` shape from `buildMCPAnalyticsGroups`.
export type FlagGroups = Record<string, string>

export async function isFeatureFlagEnabled(flagKey: string, distinctId: string, groups?: FlagGroups): Promise<boolean> {
    try {
        const client = getPostHogClient()
        const result = await client.isFeatureEnabled(flagKey, distinctId, groups ? { groups } : undefined)
        return result === true
    } catch {
        return false
    }
}

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
    if (flagKeys.length === 0) {
        return {}
    }

    const results = await Promise.all(
        flagKeys.map(async (key) => {
            const enabled = await isFeatureFlagEnabled(key, distinctId, groups)
            return [key, enabled] as const
        })
    )

    return Object.fromEntries(results)
}
