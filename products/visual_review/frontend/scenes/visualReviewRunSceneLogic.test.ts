import { expectLogic, partial } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { visualReviewRunSceneLogic } from './visualReviewRunSceneLogic'

const RUN_ID = '00000000-0000-0000-0000-0000000000aa'
const TOLERATED_URL = `/api/projects/:team_id/visual_review/runs/${RUN_ID}/tolerated-hashes/`
const SNAPSHOTS_URL = `/api/projects/:team_id/visual_review/runs/${RUN_ID}/snapshots/`
const LIFTS_URL = `/api/projects/:team_id/visual_review/runs/${RUN_ID}/quarantine_lifts/`
const CHANGED_SNAPSHOT = { id: 'snapshot-changed', identifier: 'changed', result: 'changed' }
const UNCHANGED_SNAPSHOT = { id: 'snapshot-unchanged', identifier: 'unchanged', result: 'unchanged' }

const toleratedToday = (index: number): Record<string, unknown> => ({
    id: `tolerated-${index}`,
    alternate_hash: `alt-${index}`,
    baseline_hash: 'base',
    reason: 'human',
    diff_percentage: 2.6,
    created_at: new Date().toISOString(),
    source_run_id: null,
})

describe('visualReviewRunSceneLogic', () => {
    let logic: ReturnType<typeof visualReviewRunSceneLogic.build>
    let releaseSlow: () => void = () => {}

    beforeEach(() => {
        useMocks({
            get: {
                [`/api/projects/:team_id/visual_review/runs/${RUN_ID}/`]: [404, {}],
                [SNAPSHOTS_URL]: [404, {}],
                [TOLERATED_URL]: async ({ request }) => {
                    const identifier = new URL(request.url).searchParams.get('identifier')
                    if (identifier === 'other') {
                        return [500, {}]
                    }
                    if (identifier?.startsWith('slow')) {
                        await new Promise<void>((resolve) => {
                            releaseSlow = resolve
                        })
                    }
                    if (identifier === 'slow-failing') {
                        return [500, {}]
                    }
                    const results = identifier === 'quiet' ? [] : [0, 1, 2].map(toleratedToday)
                    return [200, { count: results.length, next: null, previous: null, results }]
                },
            },
        })
        initKeaTests()
        logic = visualReviewRunSceneLogic({ runId: RUN_ID })
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
    })

    it('drops the previous snapshot tolerations when the next load fails', async () => {
        await expectLogic(logic, () => logic.actions.loadToleratedHashes('flaky'))
            .toDispatchActions(['loadToleratedHashesSuccess'])
            .toMatchValues({ recentTolerations: { manual: 3, agent: 0, auto: 0 } })

        await expectLogic(logic, () => logic.actions.loadToleratedHashes('other'))
            .toDispatchActions(['loadToleratedHashesFailure'])
            .toMatchValues({ recentTolerations: { manual: 0, agent: 0, auto: 0 } })
    })

    it('loads a deep-linked snapshot that the changes-only list leaves out', async () => {
        useMocks({
            get: {
                [SNAPSHOTS_URL]: ({ request }) => {
                    const params = new URL(request.url).searchParams
                    const results =
                        params.get('snapshot_id') === UNCHANGED_SNAPSHOT.id
                            ? [UNCHANGED_SNAPSHOT]
                            : params.get('exclude_unchanged') === 'true'
                              ? [CHANGED_SNAPSHOT]
                              : [CHANGED_SNAPSHOT, UNCHANGED_SNAPSHOT]
                    return [200, { count: results.length, next: null, previous: null, results }]
                },
            },
        })
        logic.actions.setSelectedSnapshotId(UNCHANGED_SNAPSHOT.id)

        await expectLogic(logic, () => logic.actions.loadSnapshots())
            .toDispatchActions(['loadSnapshotsSuccess', 'loadDeepLinkedSnapshotSuccess'])
            .toMatchValues({ snapshots: [CHANGED_SNAPSHOT], selectedSnapshot: UNCHANGED_SNAPSHOT })
    })

    it('shows the latest deep link when an earlier one is still loading', async () => {
        const otherUnchangedSnapshot = { id: 'snapshot-other', identifier: 'other-unchanged', result: 'unchanged' }
        let releaseFirst: () => void = () => {}
        useMocks({
            get: {
                [SNAPSHOTS_URL]: async ({ request }) => {
                    const snapshotId = new URL(request.url).searchParams.get('snapshot_id')
                    if (snapshotId === UNCHANGED_SNAPSHOT.id) {
                        await new Promise<void>((resolve) => {
                            releaseFirst = resolve
                        })
                    }
                    const results =
                        snapshotId === UNCHANGED_SNAPSHOT.id
                            ? [UNCHANGED_SNAPSHOT]
                            : snapshotId === otherUnchangedSnapshot.id
                              ? [otherUnchangedSnapshot]
                              : [CHANGED_SNAPSHOT]
                    return [200, { count: results.length, next: null, previous: null, results }]
                },
            },
        })
        logic.actions.setSelectedSnapshotId(UNCHANGED_SNAPSHOT.id)
        await expectLogic(logic, () => logic.actions.loadSnapshots()).toDispatchActions(['loadDeepLinkedSnapshot'])

        await expectLogic(logic, () => logic.actions.setSelectedSnapshotId(otherUnchangedSnapshot.id))
            .toDispatchActions(['loadDeepLinkedSnapshotSuccess'])
            .toMatchValues({ selectedSnapshot: otherUnchangedSnapshot })

        releaseFirst()
        await expectLogic(logic).toFinishAllListeners()
        await expectLogic(logic).toMatchValues({ selectedSnapshot: otherUnchangedSnapshot })
    })

    it('keeps a cached deep link when the user returns to it before a newer one loads', async () => {
        const otherUnchangedSnapshot = { id: 'snapshot-other', identifier: 'other-unchanged', result: 'unchanged' }
        let releaseOther: () => void = () => {}
        useMocks({
            get: {
                [SNAPSHOTS_URL]: async ({ request }) => {
                    const snapshotId = new URL(request.url).searchParams.get('snapshot_id')
                    if (snapshotId === otherUnchangedSnapshot.id) {
                        await new Promise<void>((resolve) => {
                            releaseOther = resolve
                        })
                    }
                    const results =
                        snapshotId === UNCHANGED_SNAPSHOT.id
                            ? [UNCHANGED_SNAPSHOT]
                            : snapshotId === otherUnchangedSnapshot.id
                              ? [otherUnchangedSnapshot]
                              : [CHANGED_SNAPSHOT]
                    return [200, { count: results.length, next: null, previous: null, results }]
                },
            },
        })
        logic.actions.setSelectedSnapshotId(UNCHANGED_SNAPSHOT.id)
        await expectLogic(logic, () => logic.actions.loadSnapshots()).toDispatchActions([
            'loadDeepLinkedSnapshotSuccess',
        ])
        await expectLogic(logic, () =>
            logic.actions.setSelectedSnapshotId(otherUnchangedSnapshot.id)
        ).toDispatchActions(['loadDeepLinkedSnapshot'])

        logic.actions.setSelectedSnapshotId(UNCHANGED_SNAPSHOT.id)
        releaseOther()
        await expectLogic(logic).toFinishAllListeners()
        await expectLogic(logic).toMatchValues({ selectedSnapshot: UNCHANGED_SNAPSHOT })
    })

    it.each([
        { slow: 'slow', fast: 'quiet', manual: 0 },
        { slow: 'slow-failing', fast: 'flaky', manual: 3 },
    ])('ignores a $slow response that lands after $fast', async ({ slow, fast, manual }) => {
        logic.actions.loadToleratedHashes(slow)
        await expectLogic(logic, () => logic.actions.loadToleratedHashes(fast))
            .toDispatchActions(['loadToleratedHashesSuccess'])
            .toMatchValues({ recentTolerations: { manual, agent: 0, auto: 0 } })

        releaseSlow()
        await expectLogic(logic).toFinishAllListeners()
        await expectLogic(logic).toMatchValues({ recentTolerations: { manual, agent: 0, auto: 0 } })
    })

    const lift = (
        id: string,
        state: string,
        runType = 'storybook',
        quarantineId = 'quarantine-active'
    ): Record<string, unknown> => ({
        id,
        identifier: 'flaky',
        quarantine_id: quarantineId,
        run_type: runType,
        state,
        detail: 'Waiting for the pull request to merge',
    })
    // Newest first, as the endpoint returns them.
    const LIFTS_WITH_PENDING = [
        lift('earlier-quarantine', 'pending', 'storybook', 'quarantine-ended'),
        lift('cancelled-newer', 'cancelled'),
        lift('other-run-type', 'pending', 'playwright'),
        lift('pending-older', 'pending'),
    ]

    it.each([
        {
            name: 'the pending request of an approved change',
            reviewState: 'approved',
            liftsResponse: [200, LIFTS_WITH_PENDING],
            selectedLiftRequest: partial({ id: 'pending-older' }),
            disabledReason: null,
        },
        {
            name: 'the pending request of a change to approve first',
            reviewState: 'pending',
            liftsResponse: [200, LIFTS_WITH_PENDING],
            selectedLiftRequest: partial({ id: 'pending-older' }),
            disabledReason: 'Approve the new picture first',
        },
        {
            name: 'no request when only an ended quarantine was lifted',
            reviewState: 'approved',
            liftsResponse: [200, [lift('applied-earlier', 'applied', 'storybook', 'quarantine-ended')]],
            selectedLiftRequest: null,
            disabledReason: null,
        },
        {
            name: 'a refresh hint when the list fails to load',
            reviewState: 'approved',
            liftsResponse: [500, {}],
            selectedLiftRequest: null,
            disabledReason: 'Could not load the lift requests of this pull request. Refresh the page.',
        },
    ])('shows $name', async ({ reviewState, liftsResponse, selectedLiftRequest, disabledReason }) => {
        const quarantined = {
            id: 'snapshot-flaky',
            identifier: 'flaky',
            result: 'changed',
            review_state: reviewState,
        }
        useMocks({
            get: {
                [`/api/projects/:team_id/visual_review/runs/${RUN_ID}/`]: [
                    200,
                    { id: RUN_ID, repo_id: 'repo', run_type: 'storybook', pr_number: 7, status: 'completed' },
                ],
                [SNAPSHOTS_URL]: [200, { count: 1, next: null, previous: null, results: [quarantined] }],
                '/api/projects/:team_id/visual_review/repos/repo/quarantine/': [
                    200,
                    {
                        count: 1,
                        next: null,
                        previous: null,
                        results: [
                            {
                                id: 'quarantine-active',
                                identifier: 'flaky',
                                run_type: 'storybook',
                                expires_at: null,
                            },
                        ],
                    },
                ],
                [LIFTS_URL]: liftsResponse as [number, unknown],
            },
        })
        logic.actions.setSelectedSnapshotId(quarantined.id)
        logic.actions.loadRun()
        logic.actions.loadSnapshots()

        await expectLogic(logic).toFinishAllListeners()
        await expectLogic(logic).toMatchValues({
            selectedLiftRequest,
            selectedLiftOnMergeDisabledReason: disabledReason,
        })
    })
})
