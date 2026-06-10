import { env } from '@/lib/env'

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

/** Raw value from posthog-node for a single flag — `true`/`false` for boolean flags, a variant string for multivariate. */
export type FlagValue = boolean | string | undefined

/** Shape returned by {@link evaluateFeatureFlags} and threaded through the tool-filtering and instructions layers. */
export type EvaluatedFlags = Record<string, FlagValue>

export async function evaluateFeatureFlags(
    flagKeys: string[],
    distinctId: string,
    groups?: FlagGroups
): Promise<EvaluatedFlags> {
    if (flagKeys.length === 0) {
        return {}
    }

    const client = getPostHogClient()
    const hasGroups = groups && Object.keys(groups).length > 0
    const allFlags = await client.getAllFlags(distinctId, { flagKeys, ...(hasGroups ? { groups } : {}) })
    const result: EvaluatedFlags = {}
    for (const key of flagKeys) {
        result[key] = allFlags[key] as FlagValue
    }
    return result
}

// Env var (or Cloudflare var) holding a JSON object of flag overrides, e.g.
// `FEATURE_FLAG_OVERRIDES={"mcp-render-ui": true, "some-flag": "variant-a"}`.
const FEATURE_FLAG_OVERRIDES_ENV = 'FEATURE_FLAG_OVERRIDES'

/** Parse a JSON object of flag overrides. Non-object JSON, parse errors, and
 *  values that aren't booleans or variant strings are ignored. */
function parseFlagOverridesJson(raw: string | undefined): EvaluatedFlags {
    if (!raw) {
        return {}
    }
    try {
        const parsed: unknown = JSON.parse(raw)
        if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
            return {}
        }
        const result: EvaluatedFlags = {}
        for (const [key, value] of Object.entries(parsed as Record<string, unknown>)) {
            if (typeof value === 'boolean' || typeof value === 'string') {
                result[key] = value
            }
        }
        return result
    } catch {
        return {}
    }
}

/**
 * Dev/test-only feature-flag overrides, merged on top of the posthog-node
 * evaluation so flags can be forced for local dev and evals — where the
 * analytics client is disabled (no `POSTHOG_ANALYTICS_*`) and every flag would
 * otherwise resolve to `false`.
 *
 * Sources, later wins: the `FEATURE_FLAG_OVERRIDES` env/Cloudflare var
 * (server-wide), then the per-request override (`?flag_overrides=` query param /
 * `x-posthog-flag-overrides` header on the Hono path). Both are JSON objects.
 *
 * Honored ONLY when NODE_ENV is explicitly `development` or `test`: without this
 * guard a request could send `?flag_overrides={"<gated-flag>":true}` to unlock
 * flag-gated tools. The positive allowlist (rather than `!== 'production'`) makes
 * the seam fail closed when NODE_ENV is unset — e.g. on Cloudflare Workers, where
 * `process.env` may be empty — mirroring `extractBearerToken` in `lib/utils`.
 */
export function resolveFeatureFlagOverrides(requestOverrides?: string): EvaluatedFlags {
    if (env.NODE_ENV !== 'development' && env.NODE_ENV !== 'test') {
        return {}
    }
    return {
        ...parseFlagOverridesJson(env[FEATURE_FLAG_OVERRIDES_ENV]),
        ...parseFlagOverridesJson(requestOverrides),
    }
}
