// The usage rollup: which caller actually read which key, and whether an in-flight
// rotation's previous value is safe to retire. Computed here, service-side, because the
// verdict must come from what this service measured — never from a client's claim.
//
// The rollup carries no credential values — caller names, key names, counts, timestamps
// and rotation state only.

import type { MountedCredentials, SecretState } from '../types'

export interface UsageCallerEntry {
    /** The calling deployment, as authenticated by its signing key. */
    caller: string
    /** Reads inside the rolling window. Zero for a deployment last seen before it. */
    reads24h: number
    lastSeen: string | null
    /** True when this deployment has read the key since the current value was activated. */
    onCurrentValue: boolean
}

export interface UsageKeyEntry {
    state: SecretState
    currentVersionId: string
    currentActivatedAt: string | null
    callers: UsageCallerEntry[]
    /**
     * True when every deployment known to read this key has read it since the secret last
     * changed, and at least one such deployment exists. "Known to read" spans every caller
     * with a last-seen record, so one that reads rarely delays the verdict rather than
     * rushing it.
     *
     * Sound only because callers do not cache: a read after activation necessarily returned
     * the new value. Reintroducing a client-side cache breaks this verdict.
     */
    safeToRetirePrevious: boolean
}

export interface UsageMap {
    generatedAt: string
    env: string
    /** Hours of quiet required before safeToRetirePrevious can be true. */
    quietWindowHours: number
    keys: Record<string, UsageKeyEntry>
}

export function buildUsageMap(opts: {
    env: string
    generatedAt: string
    quietWindowHours: number
    mounted: MountedCredentials | null
    reads: ReadonlyMap<string, number>
    lastSeen: ReadonlyMap<string, number>
}): UsageMap {
    const keys: Record<string, UsageKeyEntry> = {}
    const mounted = opts.mounted

    if (mounted) {
        for (const [key, credential] of Object.entries(mounted.credentials)) {
            const callers = new Map<string, UsageCallerEntry>()

            const ensure = (caller: string): UsageCallerEntry => {
                let entry = callers.get(caller)
                if (!entry) {
                    entry = { caller, reads24h: 0, lastSeen: null, onCurrentValue: false }
                    callers.set(caller, entry)
                }
                return entry
            }

            for (const [field, count] of opts.reads) {
                const [fieldKey, caller] = field.split('|')
                if (fieldKey === key && caller) {
                    ensure(caller).reads24h += count
                }
            }

            const activatedAt = mounted.changedAt ? Date.parse(mounted.changedAt) : null
            for (const [field, at] of opts.lastSeen) {
                const [fieldKey, caller] = field.split('|')
                // Not gated on the rolling window: dropping a deployment that reads
                // rarely would let one active caller declare the previous value retirable
                // while a dormant consumer is still on it.
                if (fieldKey === key && caller) {
                    const entry = ensure(caller)
                    entry.lastSeen = new Date(at).toISOString()
                    // No caching anywhere, so a read after activation means "has moved on".
                    entry.onCurrentValue = activatedAt !== null && at >= activatedAt
                }
            }

            const entries = [...callers.values()].sort((a, b) => a.caller.localeCompare(b.caller))

            keys[key] = {
                state: credential.state,
                currentVersionId: credential.versionId,
                currentActivatedAt: mounted.changedAt,
                callers: entries,
                safeToRetirePrevious:
                    credential.state === 'rotating' &&
                    entries.length > 0 &&
                    entries.every((entry) => entry.onCurrentValue),
            }
        }
    }

    return {
        generatedAt: opts.generatedAt,
        env: opts.env,
        quietWindowHours: opts.quietWindowHours,
        keys,
    }
}
