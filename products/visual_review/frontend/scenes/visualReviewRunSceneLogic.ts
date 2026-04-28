import { actions, afterMount, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { actionToUrl, urlToAction } from 'kea-router'

import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { teamLogic } from 'scenes/teamLogic'

import { Breadcrumb } from '~/types'

import {
    visualReviewReposQuarantineCreate,
    visualReviewReposQuarantineExpireCreate,
    visualReviewReposQuarantineList,
    visualReviewReposRetrieve,
    visualReviewRunsApproveCreate,
    visualReviewRunsRecomputeCreate,
    visualReviewRunsTolerateCreate,
    visualReviewRunsRetrieve,
    visualReviewRunsSnapshotHistoryList,
    visualReviewRunsSnapshotsList,
    visualReviewRunsToleratedHashesList,
} from '../generated/api'
import type {
    QuarantinedIdentifierEntryApi,
    RepoApi,
    RunApi,
    SnapshotApi,
    SnapshotHistoryEntryApi,
    ToleratedHashEntryApi,
} from '../generated/api.schemas'
import type { visualReviewRunSceneLogicType } from './visualReviewRunSceneLogicType'

export interface VisualReviewRunSceneLogicProps {
    runId: string
}

export const visualReviewRunSceneLogic = kea<visualReviewRunSceneLogicType>([
    path(['products', 'visual_review', 'frontend', 'scenes', 'visualReviewRunSceneLogic']),
    props({} as VisualReviewRunSceneLogicProps),
    key((props) => props.runId),
    connect(() => ({
        values: [teamLogic, ['currentProjectId']],
    })),
    actions({
        setSelectedSnapshotId: (snapshotId: string | null) => ({ snapshotId }),
        approveChanges: true,
        approveChangesSuccess: true,
        approveChangesFailure: true,
        approveSnapshot: (snapshot: SnapshotApi) => ({ snapshot }),
        approveSnapshotSuccess: true,
        approveSnapshotFailure: true,
        markAsTolerated: (snapshot: SnapshotApi) => ({ snapshot }),
        quarantineSnapshot: (reason: string, identifiers: string[], expiresAt: string | null) => ({
            reason,
            identifiers,
            expiresAt,
        }),
        unquarantineSnapshot: (snapshot: SnapshotApi) => ({ snapshot }),
        recomputeRun: true,
        recomputeRunSuccess: true,
        recomputeRunFailure: true,
        markThumbnailFailed: (identifier: string) => ({ identifier }),
    }),
    reducers({
        selectedSnapshotId: [
            null as string | null,
            {
                setSelectedSnapshotId: (_, { snapshotId }) => snapshotId,
            },
        ],
        isApproving: [
            false,
            {
                approveChanges: () => true,
                approveChangesSuccess: () => false,
                approveChangesFailure: () => false,
            },
        ],
        isApprovingSnapshot: [
            false,
            {
                approveSnapshot: () => true,
                approveSnapshotSuccess: () => false,
                approveSnapshotFailure: () => false,
            },
        ],
        isRecomputing: [
            false,
            {
                recomputeRun: () => true,
                recomputeRunSuccess: () => false,
                recomputeRunFailure: () => false,
            },
        ],
        failedThumbnails: [
            new Set<string>() as Set<string>,
            {
                markThumbnailFailed: (state: Set<string>, { identifier }: { identifier: string }) => {
                    const next = new Set(state)
                    next.add(identifier)
                    return next
                },
            },
        ],
    }),
    loaders(({ props, values }) => ({
        run: [
            null as RunApi | null,
            {
                loadRun: async () => {
                    return visualReviewRunsRetrieve(String(values.currentProjectId), props.runId)
                },
            },
        ],
        snapshots: [
            [] as SnapshotApi[],
            {
                loadSnapshots: async () => {
                    const response = await visualReviewRunsSnapshotsList(String(values.currentProjectId), props.runId, {
                        limit: 10000,
                    })
                    return response.results
                },
            },
        ],
        repo: [
            null as RepoApi | null,
            {
                loadRepo: async () => {
                    const run = values.run
                    if (!run) {
                        return null
                    }
                    return visualReviewReposRetrieve(String(values.currentProjectId), run.repo_id)
                },
            },
        ],
        snapshotHistory: [
            [] as SnapshotHistoryEntryApi[],
            {
                loadSnapshotHistory: async (identifier: string) => {
                    const response = await visualReviewRunsSnapshotHistoryList(
                        String(values.currentProjectId),
                        props.runId,
                        {
                            identifier,
                        }
                    )
                    return response.results
                },
            },
        ],
        toleratedHashes: [
            [] as ToleratedHashEntryApi[],
            {
                loadToleratedHashes: async (identifier: string) => {
                    const response = await visualReviewRunsToleratedHashesList(
                        String(values.currentProjectId),
                        props.runId,
                        { identifier }
                    )
                    return response.results
                },
            },
        ],
        quarantinedIdentifiers: [
            [] as QuarantinedIdentifierEntryApi[],
            {
                loadQuarantinedIdentifiers: async () => {
                    const run = values.run
                    if (!run) {
                        return []
                    }
                    const response = await visualReviewReposQuarantineList(
                        String(values.currentProjectId),
                        run.repo_id,
                        { run_type: run.run_type }
                    )
                    return response.results
                },
            },
        ],
    })),
    selectors({
        selectedSnapshot: [
            (s) => [s.snapshots, s.selectedSnapshotId],
            (snapshots, selectedSnapshotId): SnapshotApi | null => {
                if (!selectedSnapshotId) {
                    return snapshots.find((s) => s.result !== 'unchanged') || snapshots[0] || null
                }
                return snapshots.find((s) => s.id === selectedSnapshotId) || null
            },
        ],
        changedSnapshots: [
            (s) => [s.snapshots],
            (snapshots): SnapshotApi[] => snapshots.filter((s) => s.result !== 'unchanged'),
        ],
        sortedChangedSnapshots: [
            (s) => [s.changedSnapshots],
            (changedSnapshots: SnapshotApi[]): SnapshotApi[] => {
                // Group by base identifier (strip theme suffix like --dark / --light)
                const getBaseIdentifier = (identifier: string): string => {
                    const parts = identifier.split('--')
                    const last = parts[parts.length - 1]
                    if (last === 'dark' || last === 'light') {
                        return parts.slice(0, -1).join('--')
                    }
                    return identifier
                }

                // Group snapshots by base identifier
                const groups = new Map<string, SnapshotApi[]>()
                for (const snapshot of changedSnapshots) {
                    const base = getBaseIdentifier(snapshot.identifier)
                    const group = groups.get(base) || []
                    group.push(snapshot)
                    groups.set(base, group)
                }

                // Sort groups by max diff% descending
                const sortedGroups = [...groups.values()].sort((a, b) => {
                    const maxA = Math.max(...a.map((s) => s.diff_percentage ?? 0))
                    const maxB = Math.max(...b.map((s) => s.diff_percentage ?? 0))
                    return maxB - maxA
                })

                return sortedGroups.flat()
            },
        ],
        hasChanges: [(s) => [s.changedSnapshots], (changedSnapshots): boolean => changedSnapshots.length > 0],
        unreviewedChangesCount: [
            (s) => [s.changedSnapshots],
            (changedSnapshots): number =>
                changedSnapshots.filter((s) => s.review_state !== 'approved' && s.review_state !== 'tolerated').length,
        ],
        quarantinedIdentifierSet: [
            (s) => [s.quarantinedIdentifiers, s.run],
            (quarantinedIdentifiers: QuarantinedIdentifierEntryApi[], run: RunApi | null): Set<string> =>
                new Set(
                    quarantinedIdentifiers
                        .filter(
                            (q: QuarantinedIdentifierEntryApi) =>
                                q.run_type === run?.run_type && (!q.expires_at || new Date(q.expires_at) > new Date())
                        )
                        .map((q: QuarantinedIdentifierEntryApi) => q.identifier)
                ),
        ],
        repoFullName: [(s) => [s.repo], (repo): string | null => repo?.repo_full_name || null],
        thumbnailBasePath: [
            (s) => [s.run, s.currentProjectId],
            (run, projectId): string | null => {
                if (!run || !projectId) {
                    return null
                }
                return `/api/projects/${projectId}/visual_review/repos/${run.repo_id}/thumbnails`
            },
        ],
        isRunInProgress: [(s) => [s.run], (run): boolean => run?.status === 'pending' || run?.status === 'processing'],
        isRunProcessing: [(s) => [s.run], (run): boolean => run?.status === 'processing'],
        breadcrumbs: [
            (s) => [s.run],
            (run): Breadcrumb[] => [
                {
                    key: 'visual_review',
                    name: 'Visual review',
                    path: '/visual_review',
                },
                {
                    key: 'visual_review_run',
                    name: run?.branch || 'Run',
                },
            ],
        ],
    }),
    listeners(({ actions, values, props }) => ({
        setSelectedSnapshotId: () => {
            const snapshot = values.selectedSnapshot
            if (snapshot) {
                actions.loadSnapshotHistory(snapshot.identifier)
                actions.loadToleratedHashes(snapshot.identifier)
            }
        },
        loadRunSuccess: () => {
            actions.loadRepo()
            actions.loadQuarantinedIdentifiers()
        },
        loadSnapshotsSuccess: () => {
            const snapshot = values.selectedSnapshot
            if (snapshot) {
                actions.loadSnapshotHistory(snapshot.identifier)
                actions.loadToleratedHashes(snapshot.identifier)
            }
        },
        approveChanges: async () => {
            const { run } = values
            if (!run) {
                return
            }

            try {
                await visualReviewRunsApproveCreate(String(values.currentProjectId), props.runId, {
                    approve_all: true,
                })
                actions.approveChangesSuccess()
                lemonToast.success('Changes approved successfully')
                actions.loadRun()
                actions.loadSnapshots()
            } catch (e: any) {
                actions.approveChangesFailure()
                lemonToast.error(e?.detail || e?.message || 'Failed to approve changes')
            }
        },
        approveSnapshot: async ({ snapshot }) => {
            if (!snapshot.current_artifact?.content_hash) {
                lemonToast.error('No artifact to approve')
                actions.approveSnapshotFailure()
                return
            }

            const approvalPayload = {
                snapshots: [
                    {
                        identifier: snapshot.identifier,
                        new_hash: snapshot.current_artifact.content_hash,
                    },
                ],
            }

            // Find the next pending snapshot in sorted order before the async call
            const sorted = values.sortedChangedSnapshots
            const currentIdx = sorted.findIndex((s) => s.id === snapshot.id)
            const nextPending = sorted.slice(currentIdx + 1).find((s) => s.review_state === 'pending')

            try {
                await visualReviewRunsApproveCreate(String(values.currentProjectId), props.runId, approvalPayload)
                actions.approveSnapshotSuccess()
                lemonToast.success('Snapshot approved')
                actions.loadRun()
                actions.loadSnapshots()
                if (nextPending) {
                    actions.setSelectedSnapshotId(nextPending.id)
                }
            } catch (e: any) {
                actions.approveSnapshotFailure()
                lemonToast.error(e?.detail || e?.message || 'Failed to approve snapshot')
            }
        },
        markAsTolerated: async ({ snapshot }) => {
            try {
                await visualReviewRunsTolerateCreate(String(values.currentProjectId), props.runId, {
                    snapshot_id: snapshot.id,
                })
                lemonToast.success('Marked as tolerated')
                actions.loadRun()
                actions.loadSnapshots()
            } catch (e: any) {
                lemonToast.error(e?.detail || e?.message || 'Failed to mark as tolerated')
            }
        },
        quarantineSnapshot: async ({ reason, identifiers, expiresAt }) => {
            const { run } = values
            if (!run) {
                return
            }
            try {
                await Promise.all(
                    identifiers.map((identifier) =>
                        visualReviewReposQuarantineCreate(String(values.currentProjectId), run.repo_id, run.run_type, {
                            identifier,
                            reason,
                            expires_at: expiresAt,
                        })
                    )
                )
                const count = identifiers.length
                lemonToast.success(`${count} identifier${count > 1 ? 's' : ''} quarantined`)
                actions.loadQuarantinedIdentifiers()
            } catch (e: any) {
                lemonToast.error(e?.detail || e?.message || 'Failed to quarantine')
            }
        },
        recomputeRun: async () => {
            try {
                const result = await visualReviewRunsRecomputeCreate(String(values.currentProjectId), props.runId)
                actions.recomputeRunSuccess()

                if (result.ci_rerun_triggered) {
                    lemonToast.success(
                        result.counts_changed ? 'Counts updated, CI job re-triggered' : 'CI job re-triggered'
                    )
                } else if (result.ci_rerun_error) {
                    if (result.counts_changed) {
                        lemonToast.success('Counts updated')
                    }
                    lemonToast.warning(`CI re-trigger failed: ${result.ci_rerun_error}`)
                } else {
                    lemonToast.success(result.counts_changed ? 'Counts updated' : 'No changes needed')
                }
                actions.loadRun()
                actions.loadSnapshots()
            } catch (e: any) {
                actions.recomputeRunFailure()
                lemonToast.error(e?.detail || e?.message || 'Failed to recompute')
            }
        },
        unquarantineSnapshot: async ({ snapshot }) => {
            const { run } = values
            if (!run) {
                return
            }
            try {
                await visualReviewReposQuarantineExpireCreate(
                    String(values.currentProjectId),
                    run.repo_id,
                    run.run_type,
                    { identifier: snapshot.identifier, reason: '' }
                )
                lemonToast.success('Identifier unquarantined — future runs will gate on it again')
                actions.loadQuarantinedIdentifiers()
            } catch (e: any) {
                lemonToast.error(e?.detail || e?.message || 'Failed to unquarantine')
            }
        },
    })),
    urlToAction(({ actions, values, props }) => ({
        '/visual_review/runs/:runId': ({ runId }, _searchParams, { snapshot }) => {
            if (runId !== props.runId) {
                return
            }
            if (snapshot && snapshot !== values.selectedSnapshotId) {
                actions.setSelectedSnapshotId(snapshot)
            }
        },
    })),
    actionToUrl(({ props }) => ({
        setSelectedSnapshotId: ({ snapshotId }) => {
            if (snapshotId) {
                return [`/visual_review/runs/${props.runId}`, {}, { snapshot: snapshotId }]
            }
            return [`/visual_review/runs/${props.runId}`]
        },
    })),
    afterMount(({ actions }) => {
        actions.loadRun()
        actions.loadSnapshots()
    }),
])
