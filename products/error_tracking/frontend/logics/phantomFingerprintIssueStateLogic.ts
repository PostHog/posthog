import { actions, kea, listeners, path, reducers, selectors } from 'kea'

import api from 'lib/api'
import { ErrorTrackingFingerprint } from 'lib/components/Errors/types'

import {
    ErrorTrackingIssue,
    ErrorTrackingPhantomFingerprintIssueState,
    ErrorTrackingRelationalIssue,
} from '~/queries/schema/schema-general'

import { errorTrackingIssueSceneLogic } from '../scenes/ErrorTrackingIssueScene/errorTrackingIssueSceneLogic'
import { issuesDataNodeLogic } from './issuesDataNodeLogic'
import type { phantomFingerprintIssueStateLogicType } from './phantomFingerprintIssueStateLogicType'
import { applyDelta, buildPhantomRow, CurrentIssueState, IssueStateDelta } from './phantomHelpers'

// CH sync typically lands in seconds; 60s is generous.
export const PHANTOM_TTL_MS = 60_000

export type StoredPhantom = ErrorTrackingPhantomFingerprintIssueState & { expiresAt: number }

export const phantomFingerprintIssueStateLogic = kea<phantomFingerprintIssueStateLogicType>([
    path(['products', 'error_tracking', 'logics', 'phantomFingerprintIssueStateLogic']),

    actions({
        addPhantoms: (rows: ErrorTrackingPhantomFingerprintIssueState[]) => ({ rows }),
        capturePhantomsForIssues: (issueIds: string[], delta: IssueStateDelta) => ({ issueIds, delta }),
        captureMergePhantoms: (primaryId: string, sourceIds: string[]) => ({ primaryId, sourceIds }),
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
                    const next: Record<string, StoredPhantom> = {}
                    for (const [fp, row] of Object.entries(state)) {
                        if (row.expiresAt > now) {
                            next[fp] = row
                        }
                    }
                    for (const row of rows) {
                        const existing = next[row.fingerprint]
                        // Keep the higher-versioned row; ties favor the incoming (more recent add).
                        if (existing && existing.version > row.version) {
                            continue
                        }
                        next[row.fingerprint] = { ...row, expiresAt: now + PHANTOM_TTL_MS }
                    }
                    return next
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

    listeners(({ actions }) => {
        function findCurrentIssueState(id: string): CurrentIssueState | null {
            const detail = errorTrackingIssueSceneLogic.findMounted({ id })?.values.issue as
                | ErrorTrackingRelationalIssue
                | null
                | undefined
            if (detail && detail.id === id) {
                return {
                    id: detail.id,
                    name: detail.name ?? null,
                    description: detail.description ?? null,
                    status: detail.status,
                    assignee: detail.assignee ?? null,
                    first_seen: detail.first_seen,
                }
            }

            const listResults = (issuesDataNodeLogic.findMounted()?.values.results ?? []) as ErrorTrackingIssue[]
            const listIssue = listResults.find((i) => i.id === id)
            if (listIssue) {
                return {
                    id: listIssue.id,
                    name: listIssue.name ?? null,
                    description: listIssue.description ?? null,
                    status: listIssue.status,
                    assignee: listIssue.assignee ?? null,
                    first_seen: listIssue.first_seen,
                }
            }
            return null
        }

        async function resolveFingerprintsForIssues(
            issueIds: Array<ErrorTrackingIssue['id']>
        ): Promise<Record<string, string[]>> {
            const unique = Array.from(new Set(issueIds))
            const result: Record<string, string[]> = {}

            const toFetch: string[] = []
            for (const id of unique) {
                const mounted = errorTrackingIssueSceneLogic.findMounted({ id })
                const loaded = mounted?.values.issueFingerprints
                if (mounted && Array.isArray(loaded) && loaded.length > 0) {
                    result[id] = loaded.map((f) => f.fingerprint)
                } else {
                    toFetch.push(id)
                }
            }

            if (toFetch.length > 0) {
                const responses = await Promise.all(
                    toFetch.map((id) =>
                        api.errorTracking.fingerprints
                            .list(id)
                            .then((rows: ErrorTrackingFingerprint[]) => [id, rows.map((r) => r.fingerprint)] as const)
                            .catch(() => [id, [] as string[]] as const)
                    )
                )
                for (const [id, fingerprints] of responses) {
                    result[id] = fingerprints
                }
            }

            return result
        }

        return {
            capturePhantomsForIssues: async ({ issueIds, delta }) => {
                const uniqueIds = Array.from(new Set(issueIds)).filter(Boolean)
                if (uniqueIds.length === 0) {
                    return
                }

                const fingerprintMap = await resolveFingerprintsForIssues(uniqueIds)
                const version = Date.now()
                const rows: ErrorTrackingPhantomFingerprintIssueState[] = []

                for (const id of uniqueIds) {
                    const current = findCurrentIssueState(id)
                    if (!current) {
                        continue
                    }
                    const merged = applyDelta(current, delta)
                    const fingerprints = fingerprintMap[id] ?? []
                    for (const fp of fingerprints) {
                        rows.push(buildPhantomRow(fp, id, merged, version))
                    }
                }

                if (rows.length > 0) {
                    actions.addPhantoms(rows)
                }
            },
            captureMergePhantoms: async ({ primaryId, sourceIds }) => {
                const allIds = Array.from(new Set([primaryId, ...sourceIds])).filter(Boolean)
                if (allIds.length === 0) {
                    return
                }

                const primaryState = findCurrentIssueState(primaryId)
                if (!primaryState) {
                    return
                }

                const fingerprintMap = await resolveFingerprintsForIssues(allIds)
                const version = Date.now()
                const rows: ErrorTrackingPhantomFingerprintIssueState[] = []

                for (const id of allIds) {
                    const fingerprints = fingerprintMap[id] ?? []
                    for (const fp of fingerprints) {
                        rows.push(buildPhantomRow(fp, primaryId, primaryState, version))
                    }
                }

                if (rows.length > 0) {
                    actions.addPhantoms(rows)
                }
            },
        }
    }),
])
