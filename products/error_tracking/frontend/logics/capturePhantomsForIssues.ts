import {
    ErrorTrackingIssue,
    ErrorTrackingIssueAssignee,
    ErrorTrackingIssueStatus,
    ErrorTrackingPhantomFingerprintIssueState,
    ErrorTrackingRelationalIssue,
} from '~/queries/schema/schema-general'

import { errorTrackingIssueSceneLogic } from '../scenes/ErrorTrackingIssueScene/errorTrackingIssueSceneLogic'
import { issuesDataNodeLogic } from './issuesDataNodeLogic'
import { phantomFingerprintIssueStateLogic } from './phantomFingerprintIssueStateLogic'
import { resolveFingerprintsForIssues } from './resolveFingerprintsForIssues'

export interface IssueStateDelta {
    status?: ErrorTrackingIssueStatus
    name?: string | null
    description?: string | null
    assignee?: ErrorTrackingIssueAssignee | null
}

interface CurrentIssueState {
    id: string
    name: string | null
    description: string | null
    status: ErrorTrackingIssueStatus
    assignee: ErrorTrackingIssueAssignee | null
    first_seen: string
}

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

    const listLogic = issuesDataNodeLogic.findMounted()
    const listResults = (listLogic?.values.results ?? []) as ErrorTrackingIssue[]
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

function buildPhantomRow(
    fingerprint: string,
    issueId: string,
    state: CurrentIssueState,
    version: number
): ErrorTrackingPhantomFingerprintIssueState {
    const assignee = state.assignee
    return {
        fingerprint,
        issue_id: issueId,
        issue_name: state.name ?? null,
        issue_description: state.description ?? null,
        issue_status: state.status,
        assigned_user_id: assignee?.type === 'user' ? (assignee.id as unknown as number) : null,
        assigned_role_id: assignee?.type === 'role' ? (assignee.id as unknown as string) : null,
        first_seen: state.first_seen,
        is_deleted: 0,
        version,
    }
}

function pushPhantoms(rows: ErrorTrackingPhantomFingerprintIssueState[]): void {
    if (rows.length === 0) {
        return
    }
    phantomFingerprintIssueStateLogic.findMounted()?.actions.addPhantoms(rows) ??
        phantomFingerprintIssueStateLogic.actions.addPhantoms(rows)
}

/**
 * Fan out a post-mutation delta over every fingerprint of the affected issues
 * and stash the resulting phantom rows into the frontend cache. The cache is
 * then UNIONed into the issues list query subquery, hiding Kafka→CH sync lag.
 *
 * Errors are swallowed — this is a nice-to-have optimization, not a correctness
 * requirement. The blocking reload still runs either way.
 */
export async function capturePhantomsForIssues(issueIds: string[], delta: IssueStateDelta): Promise<void> {
    try {
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
            const merged: CurrentIssueState = {
                ...current,
                status: delta.status ?? current.status,
                name: delta.name !== undefined ? delta.name : current.name,
                description: delta.description !== undefined ? delta.description : current.description,
                assignee: delta.assignee !== undefined ? delta.assignee : current.assignee,
            }
            const fingerprints = fingerprintMap[id] ?? []
            for (const fp of fingerprints) {
                rows.push(buildPhantomRow(fp, id, merged, version))
            }
        }

        pushPhantoms(rows)
    } catch {
        // swallow — phantom cache is best-effort
    }
}

/**
 * Merge variant: all source fingerprints get remapped to the primary issue id
 * with the primary's current state. On success the source issues disappear
 * from the list and the target absorbs their fingerprints.
 */
export async function captureMergePhantoms(primaryId: string, sourceIds: string[]): Promise<void> {
    try {
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

        pushPhantoms(rows)
    } catch {
        // swallow — phantom cache is best-effort
    }
}
