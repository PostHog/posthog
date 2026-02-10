import { actions, afterMount, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { actionToUrl, urlToAction } from 'kea-router'

import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'

import { Breadcrumb } from '~/types'

import {
    visualReviewRunsApproveCreate,
    visualReviewRunsRetrieve,
    visualReviewRunsSnapshotsList,
} from '../generated/api'
import type { ApproveSnapshotInputApi, RunApi, SnapshotApi } from '../generated/api.schemas'
import type { visualReviewRunSceneLogicType } from './visualReviewRunSceneLogicType'

export interface VisualReviewRunSceneLogicProps {
    runId: string
}

export const visualReviewRunSceneLogic = kea<visualReviewRunSceneLogicType>([
    path(['products', 'visual_review', 'frontend', 'scenes', 'visualReviewRunSceneLogic']),
    props({} as VisualReviewRunSceneLogicProps),
    key((props) => props.runId),
    actions({
        setSelectedSnapshotId: (snapshotId: string | null) => ({ snapshotId }),
        approveChanges: true,
        approveSnapshot: (snapshot: SnapshotApi) => ({ snapshot }),
    }),
    reducers({
        selectedSnapshotId: [
            null as string | null,
            {
                setSelectedSnapshotId: (_, { snapshotId }) => snapshotId,
            },
        ],
    }),
    loaders(({ props }) => ({
        run: [
            null as RunApi | null,
            {
                loadRun: async () => {
                    return visualReviewRunsRetrieve('@current', props.runId)
                },
            },
        ],
        snapshots: [
            [] as SnapshotApi[],
            {
                loadSnapshots: async () => {
                    const response = await visualReviewRunsSnapshotsList('@current', props.runId)
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
        hasChanges: [(s) => [s.changedSnapshots], (changedSnapshots): boolean => changedSnapshots.length > 0],
        unapprovedChangesCount: [
            (s) => [s.changedSnapshots],
            (changedSnapshots): number => changedSnapshots.filter((s) => s.review_state !== 'approved').length,
        ],
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
        approveChanges: async () => {
            const { changedSnapshots, run } = values
            if (!run || changedSnapshots.length === 0) {
                return
            }

            // Only approve snapshots that have a current artifact with a hash
            const approvableSnapshots = changedSnapshots.filter((s) => s.current_artifact?.content_hash)
            if (approvableSnapshots.length === 0) {
                lemonToast.error('No snapshots with artifacts to approve')
                return
            }

            const approvalPayload = {
                snapshots: approvableSnapshots.map(
                    (s): ApproveSnapshotInputApi => ({
                        identifier: s.identifier,
                        new_hash: s.current_artifact.content_hash,
                    })
                ),
            }

            try {
                await visualReviewRunsApproveCreate('@current', props.runId, approvalPayload)
                lemonToast.success('Changes approved successfully')
                actions.loadRun()
                actions.loadSnapshots()
            } catch {
                lemonToast.error('Failed to approve changes')
            }
        },
        approveSnapshot: async ({ snapshot }) => {
            if (!snapshot.current_artifact?.content_hash) {
                lemonToast.error('No artifact to approve')
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

            try {
                await visualReviewRunsApproveCreate('@current', props.runId, approvalPayload)
                lemonToast.success('Snapshot approved')
                actions.loadRun()
                actions.loadSnapshots()
            } catch {
                lemonToast.error('Failed to approve snapshot')
            }
        },
    })),
    urlToAction(({ actions, values }) => ({
        '/visual_review/runs/:runId': (_params, { snapshot }) => {
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
