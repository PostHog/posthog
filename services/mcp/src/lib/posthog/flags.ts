import { getPostHogClient } from './client'

/**
 * Group context for posthog-node flag evaluation. The keys are PostHog group
 * types (e.g. `organization`, `project`) and the values are the group keys —
 * same shape we already use for `$groups` on analytics events
 * (`buildMCPAnalyticsGroups`). Lets per-organization (and per-project) feature
 * flags resolve correctly when the rollout is keyed off a group instead of the
 * user.
 */
export type FlagGroups = Record<string, string>

export async function isFeatureFlagEnabled(flagKey: string, distinctId: string, groups?: FlagGroups): Promise<boolean> {
    try {
        const client = getPostHogClient()
        const hasGroups = groups && Object.keys(groups).length > 0
        const result = hasGroups
            ? await client.isFeatureEnabled(flagKey, distinctId, { groups })
            : await client.isFeatureEnabled(flagKey, distinctId)
        return result === true
    } catch {
        return false
    }
}

/**
 * Evaluate multiple feature flags in parallel for the given user.
 * Returns a map of flag key → boolean.
 *
 * `groups` is forwarded to posthog-node so flags rolled out at a group level
 * (e.g. per-organization) evaluate against the resolved workspace context
 * rather than the user alone.
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
