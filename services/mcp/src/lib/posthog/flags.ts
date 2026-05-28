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

export async function evaluateFeatureFlags(
    flagKeys: string[],
    distinctId: string,
    groups?: FlagGroups
): Promise<Record<string, boolean>> {
    if (flagKeys.length === 0) {
        return {}
    }

    const client = getPostHogClient()
    const hasGroups = groups && Object.keys(groups).length > 0
    const allFlags = await client.getAllFlags(distinctId, { flagKeys, ...(hasGroups ? { groups } : {}) })
    const result: Record<string, boolean> = {}
    for (const key of flagKeys) {
        result[key] = allFlags[key] === true
    }
    return result
}
