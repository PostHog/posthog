import { actions, kea, listeners, path, reducers, selectors } from 'kea'

import api from 'lib/api'
import { ErrorTrackingFingerprint } from 'lib/components/Errors/types'

import {
    ErrorTrackingIssue,
    ErrorTrackingPendingFingerprintIssueStateUpdate,
    ErrorTrackingRelationalIssue,
} from '~/queries/schema/schema-general'

import { errorTrackingIssueSceneLogic } from '../scenes/ErrorTrackingIssueScene/errorTrackingIssueSceneLogic'
import { issuesDataNodeLogic } from './issuesDataNodeLogic'
import type { pendingFingerprintIssueStateUpdateLogicType } from './pendingFingerprintIssueStateUpdateLogicType'
import { applyDelta, buildPendingUpdate, CurrentIssueState, IssueStateDelta } from './pendingUpdateHelpers'

// CH sync typically lands in seconds; 60s is generous.
export const PENDING_UPDATE_TTL_MS = 60_000

export type StoredPendingUpdate = ErrorTrackingPendingFingerprintIssueStateUpdate & { expiresAt: number }

export const pendingFingerprintIssueStateUpdateLogic = kea<pendingFingerprintIssueStateUpdateLogicType>([
    path(['products', 'error_tracking', 'logics', 'pendingFingerprintIssueStateUpdateLogic']),

    actions({
        addPendingUpdates: (rows: ErrorTrackingPendingFingerprintIssueStateUpdate[]) => ({ rows }),
        capturePendingUpdatesForIssues: (issueIds: string[], delta: IssueStateDelta) => ({ issueIds, delta }),
        captureMergePendingUpdates: (primaryId: string, sourceIds: string[]) => ({ primaryId, sourceIds }),
        clearAll: true,
    }),

    reducers({
        pendingUpdates: [
            {} as Record<string, StoredPendingUpdate>,
            {
                addPendingUpdates: (state, { rows }) => {
                    if (!rows || rows.length === 0) {
                        return state
                    }
                    const now = Date.now()
                    const next: Record<string, StoredPendingUpdate> = {}
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
                        next[row.fingerprint] = { ...row, expiresAt: now + PENDING_UPDATE_TTL_MS }
                    }
                    return next
                },
                clearAll: () => ({}),
            },
        ],
    }),

    selectors({
        currentPendingUpdates: [
            (s) => [s.pendingUpdates],
            (pendingUpdates): ErrorTrackingPendingFingerprintIssueStateUpdate[] => {
                const now = Date.now()
                const rows: ErrorTrackingPendingFingerprintIssueStateUpdate[] = []
                for (const row of Object.values(pendingUpdates)) {
                    if (row.expiresAt > now) {
                        const { expiresAt: _expiresAt, ...rest } = row
                        rows.push(rest)
                    }
                }
                return rows
            },
        ],
    }),

    listeners(({ actions }) => ({
        capturePendingUpdatesForIssues: async ({ issueIds, delta }) => {
            const uniqueIds = Array.from(new Set(issueIds)).filter(Boolean)
            if (uniqueIds.length === 0) {
                return
            }
            const fingerprintMap = await resolveFingerprintsForIssues(uniqueIds)
            const rows = buildCaptureRows(uniqueIds, fingerprintMap, delta)
            if (rows.length > 0) {
                actions.addPendingUpdates(rows)
            }
        },
        captureMergePendingUpdates: async ({ primaryId, sourceIds }) => {
            const allIds = Array.from(new Set([primaryId, ...sourceIds])).filter(Boolean)
            const primaryState = allIds.length > 0 ? findCurrentIssueState(primaryId) : null
            if (!primaryState) {
                return
            }
            const fingerprintMap = await resolveFingerprintsForIssues(allIds)
            const rows = buildMergeRows(allIds, fingerprintMap, primaryId, primaryState)
            if (rows.length > 0) {
                actions.addPendingUpdates(rows)
            }
        },
    })),
])

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

function buildCaptureRows(
    issueIds: string[],
    fingerprintMap: Record<string, string[]>,
    delta: IssueStateDelta
): ErrorTrackingPendingFingerprintIssueStateUpdate[] {
    const version = Date.now()
    const rows: ErrorTrackingPendingFingerprintIssueStateUpdate[] = []
    for (const id of issueIds) {
        const current = findCurrentIssueState(id)
        if (!current) {
            continue
        }
        const merged = applyDelta(current, delta)
        for (const fp of fingerprintMap[id] ?? []) {
            rows.push(buildPendingUpdate(fp, id, merged, version))
        }
    }
    return rows
}

function buildMergeRows(
    allIds: string[],
    fingerprintMap: Record<string, string[]>,
    primaryId: string,
    primaryState: CurrentIssueState
): ErrorTrackingPendingFingerprintIssueStateUpdate[] {
    const version = Date.now()
    const rows: ErrorTrackingPendingFingerprintIssueStateUpdate[] = []
    for (const id of allIds) {
        for (const fp of fingerprintMap[id] ?? []) {
            rows.push(buildPendingUpdate(fp, primaryId, primaryState, version))
        }
    }
    return rows
}
