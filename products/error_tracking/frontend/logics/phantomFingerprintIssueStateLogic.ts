import { actions, afterMount, kea, listeners, path, reducers, selectors } from 'kea'

import { ErrorTrackingPhantomFingerprintIssueState } from '~/queries/schema/schema-general'

import type { phantomFingerprintIssueStateLogicType } from './phantomFingerprintIssueStateLogicType'

// How long a client-side phantom row sticks around before being considered
// irrelevant. CH sync typically lands in seconds; 60s is generous.
export const PHANTOM_TTL_MS = 60_000
const PRUNE_INTERVAL_MS = 10_000

type StoredPhantom = ErrorTrackingPhantomFingerprintIssueState & { expiresAt: number }

export const phantomFingerprintIssueStateLogic = kea<phantomFingerprintIssueStateLogicType>([
    path(['products', 'error_tracking', 'logics', 'phantomFingerprintIssueStateLogic']),

    actions({
        addPhantoms: (rows: ErrorTrackingPhantomFingerprintIssueState[]) => ({ rows }),
        pruneExpired: true,
        clearAll: true,
    }),

    reducers({
        phantoms: [
            {} as Record<string, StoredPhantom>,
            {
                addPhantoms: (state, { rows }) => {
                    if (!rows || rows.length === 0) {
                        return state
                    }
                    const now = Date.now()
                    const next = { ...state }
                    for (const row of rows) {
                        const existing = next[row.fingerprint]
                        // Keep the higher-versioned row. If versions tie, the
                        // incoming one wins (more recent add).
                        if (existing && existing.version > row.version) {
                            continue
                        }
                        next[row.fingerprint] = { ...row, expiresAt: now + PHANTOM_TTL_MS }
                    }
                    return next
                },
                pruneExpired: (state) => {
                    const now = Date.now()
                    let changed = false
                    const next: Record<string, StoredPhantom> = {}
                    for (const [fp, row] of Object.entries(state)) {
                        if (row.expiresAt > now) {
                            next[fp] = row
                        } else {
                            changed = true
                        }
                    }
                    return changed ? next : state
                },
                clearAll: () => ({}),
            },
        ],
    }),

    selectors({
        currentPhantoms: [
            (s) => [s.phantoms],
            (phantoms): ErrorTrackingPhantomFingerprintIssueState[] => {
                const now = Date.now()
                const rows: ErrorTrackingPhantomFingerprintIssueState[] = []
                for (const row of Object.values(phantoms)) {
                    if (row.expiresAt > now) {
                        const { expiresAt: _expiresAt, ...rest } = row
                        rows.push(rest)
                    }
                }
                return rows
            },
        ],
    }),

    listeners(({ actions, values, cache }) => ({
        addPhantoms: () => {
            // Schedule a prune once the earliest entry expires so subscribers
            // stop receiving stale rows even without other cache activity.
            if (cache.pruneTimer) {
                return
            }
            cache.pruneTimer = window.setInterval(() => {
                actions.pruneExpired()
                if (Object.keys(values.phantoms).length === 0 && cache.pruneTimer) {
                    window.clearInterval(cache.pruneTimer)
                    cache.pruneTimer = undefined
                }
            }, PRUNE_INTERVAL_MS)
        },
    })),

    afterMount(({ cache }) => {
        cache.disposables = cache.disposables ?? new Set<() => void>()
        cache.disposables.add(() => {
            if (cache.pruneTimer) {
                window.clearInterval(cache.pruneTimer)
                cache.pruneTimer = undefined
            }
        })
    }),
])
