import type { FlagDefinitionsSnapshot, LocalFlagDefinition, LocalFlagGroup } from './flag-cache'

/**
 * Local boolean feature flag evaluation.
 *
 * Matches posthog-python / posthog-node's rollout hashing byte-for-byte:
 *   hash = sha1(`${flagKey}.${distinctId}`)
 *   bucket = int(hash[:15], 16) / 0xfffffffffffffff
 *   matches if bucket <= rollout_percentage / 100
 *
 * Returns `undefined` when the flag can't be decided locally (caller should
 * fall back to posthog-node remote evaluation). This includes:
 *   - flag missing from snapshot
 *   - flag is multivariate (caller asked for boolean)
 *   - flag targets by person properties (we don't pass them at init)
 *   - flag targets a cohort
 *   - flag is group-aggregated
 *   - flag has experience continuity or encrypted payloads (opt-out)
 *   - any unexpected filter shape
 */
export async function evaluateFlagLocally(
    snapshot: FlagDefinitionsSnapshot | null,
    flagKey: string,
    distinctId: string
): Promise<boolean | undefined> {
    if (!snapshot) {
        return undefined
    }
    const flag = snapshot.flags.find((f) => f.key === flagKey)
    if (!flag) {
        return undefined
    }
    if (flag.deleted || !flag.active) {
        return false
    }
    if (flag.ensure_experience_continuity || flag.has_encrypted_payloads) {
        return undefined
    }
    const filters = flag.filters ?? {}
    if (filters.aggregation_group_type_index != null) {
        return undefined
    }
    if (
        filters.multivariate &&
        Array.isArray(filters.multivariate.variants) &&
        filters.multivariate.variants.length > 0
    ) {
        return undefined
    }
    const groups = Array.isArray(filters.groups) ? filters.groups : []
    if (groups.length === 0) {
        return false
    }

    let anyUndecided = false
    for (const group of groups) {
        const decision = await evaluateGroup(group, flagKey, distinctId)
        if (decision === true) {
            return true
        }
        if (decision === undefined) {
            anyUndecided = true
        }
    }
    // All groups decided and none matched → flag is off.
    // Some groups undecided → we can't be sure the flag is off; fall back.
    return anyUndecided ? undefined : false
}

async function evaluateGroup(group: LocalFlagGroup, flagKey: string, distinctId: string): Promise<boolean | undefined> {
    // Any property-based filtering is out-of-scope for MVP (we don't pass person props).
    if (Array.isArray(group.properties) && group.properties.length > 0) {
        return undefined
    }
    if (group.variant) {
        // Variant override — we're answering a boolean, let remote decide.
        return undefined
    }
    const rollout = group.rollout_percentage
    // PostHog default: missing/null rollout_percentage = 100%.
    const pct = rollout == null ? 100 : Number(rollout)
    if (!Number.isFinite(pct)) {
        return undefined
    }
    if (pct >= 100) {
        return true
    }
    if (pct <= 0) {
        return false
    }
    const bucket = await computeHashBucket(flagKey, distinctId)
    return bucket <= pct / 100
}

/**
 * posthog-python / posthog-node hashing:
 *   sha1("{flagKey}.{distinctId}").hexdigest()
 *   int(hash[:15], 16) / 0xfffffffffffffff
 *
 * Uses Web Crypto's subtle.digest (available in Workers + Node 19+).
 */
export async function computeHashBucket(flagKey: string, distinctId: string): Promise<number> {
    const input = `${flagKey}.${distinctId}`
    const data = new TextEncoder().encode(input)
    const digest = await crypto.subtle.digest('SHA-1', data)
    const hex = bufferToHex(digest)
    // First 15 hex chars = 60 bits. BigInt to avoid precision loss.
    const numerator = BigInt('0x' + hex.slice(0, 15))
    const denominator = BigInt('0xfffffffffffffff')
    // Convert to Number carefully: bucket is in [0, 1], so scaling by 1e12 is safe.
    const scaled = Number((numerator * 1_000_000_000_000n) / denominator)
    return scaled / 1_000_000_000_000
}

function bufferToHex(buffer: ArrayBuffer): string {
    const bytes = new Uint8Array(buffer)
    let hex = ''
    for (let i = 0; i < bytes.length; i++) {
        hex += (bytes[i] as number).toString(16).padStart(2, '0')
    }
    return hex
}

// Re-export for tests that want to assert on definitions.
export type { LocalFlagDefinition }
