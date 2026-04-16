import { actions, afterMount, beforeUnmount, kea, path, reducers, selectors } from 'kea'

import api from 'lib/api'

import { ErrorTrackingFingerprintIssueStatePhantomRow, ErrorTrackingIssueStatus } from '~/queries/schema/schema-general'

import type { phantomFingerprintStatesLogicType } from './phantomFingerprintStatesLogicType'

// How long a phantom row stays in memory after being written. Sized to cover typical Kafka →
// ClickHouse ingestion lag for `error_tracking_fingerprint_issue_state` with a safety margin.
export const PHANTOM_TTL_MS = 60_000
// Run the sweeper twice per TTL window so expired rows are dropped promptly without burning CPU.
const PHANTOM_SWEEP_INTERVAL_MS = 10_000
// Upper bound on rows we hold per user. Matches the backend cap so pruning on write keeps SQL bounded.
const MAX_PHANTOM_ROWS = 500

/** Subset of the real fingerprint_issue_state columns the UI is allowed to override. */
export interface PhantomStateOverrides {
    issue_id?: string
    issue_status?: ErrorTrackingIssueStatus | null
    issue_name?: string | null
    issue_description?: string | null
    assigned_user_id?: number | null
    assigned_role_id?: string | null
    is_deleted?: 0 | 1
}

interface StoredPhantom extends ErrorTrackingFingerprintIssueStatePhantomRow {
    /** Epoch ms when this row was written; used for TTL eviction. */
    writtenAt: number
}

type PhantomMap = Record<string, StoredPhantom>

function mergePhantom(existing: StoredPhantom | undefined, next: StoredPhantom): StoredPhantom {
    // Phantoms are last-write-wins per fingerprint. `version` is monotonically increasing on the
    // producing client, so keep whichever row has the higher version to survive out-of-order writes.
    if (existing && existing.version >= next.version) {
        return existing
    }
    return next
}

function pruneExpired(map: PhantomMap, now: number): PhantomMap {
    const next: PhantomMap = {}
    for (const [fingerprint, row] of Object.entries(map)) {
        if (now - row.writtenAt < PHANTOM_TTL_MS) {
            next[fingerprint] = row
        }
    }
    return next
}

function enforceCap(map: PhantomMap, cap: number): PhantomMap {
    const entries = Object.entries(map)
    if (entries.length <= cap) {
        return map
    }
    // Keep the newest rows — they reflect the most recent user intent.
    entries.sort(([, a], [, b]) => b.writtenAt - a.writtenAt)
    const next: PhantomMap = {}
    for (const [fingerprint, row] of entries.slice(0, cap)) {
        next[fingerprint] = row
    }
    return next
}

/**
 * Build phantom rows for every fingerprint of an issue.
 *
 * Exposed as a plain helper (rather than only an action) so callers can `await` the fingerprint
 * fetch and guarantee the phantom rows are in the store before triggering a reload. A pure
 * action-only dispatch would race with the subsequent `reloadData` — the reload is kicked off
 * synchronously from the mutation listener and would miss phantoms that resolve asynchronously.
 */
export async function buildPhantomRowsForIssue(
    issueId: string,
    overrides: PhantomStateOverrides,
    options: { fingerprints?: string[] } = {}
): Promise<ErrorTrackingFingerprintIssueStatePhantomRow[]> {
    let fingerprints = options.fingerprints
    if (!fingerprints || fingerprints.length === 0) {
        try {
            const loaded = await api.errorTracking.fingerprints.list(issueId)
            fingerprints = loaded.map((f) => f.fingerprint)
        } catch {
            // Best-effort — if fingerprints can't be fetched, we simply skip the phantom. The real
            // state will still surface once Kafka catches up.
            return []
        }
    }
    if (fingerprints.length === 0) {
        return []
    }
    const version = Date.now()
    return fingerprints.map((fingerprint) => ({
        fingerprint,
        issue_id: overrides.issue_id ?? issueId,
        version,
        issue_status: overrides.issue_status ?? null,
        issue_name: overrides.issue_name ?? null,
        issue_description: overrides.issue_description ?? null,
        assigned_user_id: overrides.assigned_user_id ?? null,
        assigned_role_id: overrides.assigned_role_id ?? null,
        is_deleted: overrides.is_deleted ?? 0,
    }))
}

/**
 * In-memory store of phantom `error_tracking_fingerprint_issue_state` rows. Callers write rows
 * after UI mutations so that the next list-query UNIONs them into the argmax subquery and the
 * freshly mutated state wins over stale ClickHouse data while Kafka is catching up.
 *
 * `team_id` is never tracked here — the backend injects it from the authenticated context. Rows
 * expire via {@link PHANTOM_TTL_MS} and a sweeper reducer.
 */
export const phantomFingerprintStatesLogic = kea<phantomFingerprintStatesLogicType>([
    path(['products', 'error_tracking', 'logics', 'phantomFingerprintStatesLogic']),

    actions({
        writePhantoms: (rows: ErrorTrackingFingerprintIssueStatePhantomRow[]) => ({ rows, now: Date.now() }),
        sweepExpired: () => ({ now: Date.now() }),
        clearAll: true,
    }),

    reducers({
        phantomsByFingerprint: [
            {} as PhantomMap,
            {
                writePhantoms: (state, { rows, now }) => {
                    if (rows.length === 0) {
                        return state
                    }
                    let next = { ...state }
                    for (const row of rows) {
                        next[row.fingerprint] = mergePhantom(next[row.fingerprint], {
                            ...row,
                            writtenAt: now,
                        })
                    }
                    next = pruneExpired(next, now)
                    next = enforceCap(next, MAX_PHANTOM_ROWS)
                    return next
                },
                sweepExpired: (state, { now }) => pruneExpired(state, now),
                clearAll: () => ({}),
            },
        ],
    }),

    selectors({
        allPhantoms: [
            (s) => [s.phantomsByFingerprint],
            (phantomsByFingerprint): ErrorTrackingFingerprintIssueStatePhantomRow[] => {
                return Object.values(phantomsByFingerprint).map(({ writtenAt: _writtenAt, ...row }) => row)
            },
        ],
    }),

    afterMount(({ actions, cache }) => {
        cache.sweepInterval = setInterval(() => {
            actions.sweepExpired()
        }, PHANTOM_SWEEP_INTERVAL_MS)
    }),

    beforeUnmount(({ cache }) => {
        if (cache.sweepInterval) {
            clearInterval(cache.sweepInterval)
            cache.sweepInterval = undefined
        }
    }),
])
