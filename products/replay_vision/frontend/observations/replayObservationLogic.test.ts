import { waitFor } from '@testing-library/react'
import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { lemonToast } from 'lib/lemon-ui/LemonToast'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import type { ReplayObservationApi, VisionObservationsRetrieveParams } from '../generated/api.schemas'
import { neighborsFromPage, replayObservationLogic } from './replayObservationLogic'
import { type ObservationsPage, lastObservationsPage } from './replayObservationSceneLogic'
import { replayObservationSceneLogic } from './replayObservationSceneLogic'

jest.mock('lib/lemon-ui/LemonToast', () => ({
    lemonToast: { success: jest.fn(), info: jest.fn(), warning: jest.fn(), error: jest.fn() },
}))

describe('replayObservationLogic', () => {
    let retrySpy: jest.Mock
    let viewedSpy: jest.Mock
    let retrieveUrls: string[]
    let retrieveStatus: number
    let scannerOrigin: 'configured' | 'inline'
    let observationStatus: 'failed' | 'running'
    let sceneLogic: ReturnType<typeof replayObservationSceneLogic.build>

    beforeEach(() => {
        scannerOrigin = 'configured'
        observationStatus = 'failed'
        retrySpy = jest.fn(() => [202, { workflow_id: 'wf-retry' }])
        viewedSpy = jest.fn(() => [204])
        retrieveUrls = []
        retrieveStatus = 200
        lastObservationsPage.current = null
        jest.clearAllMocks()
        useMocks({
            get: {
                '/api/projects/:team/vision/observations/:id/': ({ request }) => {
                    retrieveUrls.push(request.url)
                    return [
                        retrieveStatus,
                        {
                            id: 'obs-1',
                            scanner_id: 'scanner-9',
                            scanner_origin: scannerOrigin,
                            session_id: 'sess-1',
                            status: observationStatus,
                            error_reason: 'internal_error:boom',
                            scanner_snapshot: {
                                // An inline scanner carries no name.
                                name: scannerOrigin === 'configured' ? 'My scanner' : '',
                                scanner_type: 'monitor',
                                scanner_version: 1,
                                model: 'm',
                                provider: 'p',
                                emits_signals: false,
                                scanner_config: { prompt: 'q' },
                            },
                            scanner_result: null,
                            triggered_by: 'schedule',
                            viewed: false,
                            previous_observation_id: 'prev-from-retrieve',
                            next_observation_id: 'next-from-retrieve',
                            created_at: '2026-07-01T00:00:00Z',
                        },
                    ]
                },
            },
            post: {
                '/api/projects/:team/vision/observations/:id/retry/': retrySpy,
                '/api/projects/:team/vision/observations/:id/viewed/': viewedSpy,
            },
        })
        initKeaTests()
        sceneLogic = replayObservationSceneLogic()
        sceneLogic.mount()
    })

    afterEach(() => {
        sceneLogic?.unmount()
    })

    test.each([
        { params: {}, expected: {} },
        { params: { tab: 'observations', order_by: '-created_at' }, expected: {} },
        { params: { order_by: '-created_at', status: 'succeeded' }, expected: { status: 'succeeded' } },
        { params: { order_by: 'created_at' }, expected: { order_by: 'created_at' } },
        {
            params: { order_by: '-result_score', min_score: '0', max_score: '8.5', verdict: 'yes', tags: 'checkout' },
            expected: { order_by: '-result_score', min_score: '0', max_score: '8.5', verdict: 'yes', tags: 'checkout' },
        },
        {
            params: {
                triggered_by: 'schedule',
                session_id: 'session-example',
                recording_subject: 'example',
                labeled: 'true',
            },
            expected: {
                triggered_by: 'schedule',
                session_id: 'session-example',
                recording_subject: 'example',
                labeled: 'true',
            },
        },
    ])('preserves detail request semantics for $params', async ({ params, expected }) => {
        router.actions.push('/replay-vision/observations/obs-1', params)
        const logic = replayObservationLogic({ id: 'obs-1' })
        logic.mount()
        try {
            await expectLogic(logic).toDispatchActions(['loadObservationSuccess'])
            expect(retrieveUrls.map((url) => Object.fromEntries(new URL(url).searchParams))).toEqual([expected])
        } finally {
            logic.unmount()
        }
    })

    test.each([
        { status: 'failed' as const, marks: true },
        { status: 'running' as const, marks: false },
    ])('$status observation marks viewed: $marks', async ({ status, marks }) => {
        observationStatus = status
        const logic = replayObservationLogic({ id: 'obs-1' })
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadObservationSuccess'])
        if (marks) {
            await expectLogic(logic).toDispatchActions(['markViewed'])
            await waitFor(() => expect(viewedSpy).toHaveBeenCalledTimes(1))
        } else {
            await expectLogic(logic).toNotHaveDispatchedActions(['markViewed'])
            expect(viewedSpy).not.toHaveBeenCalled()
        }
        logic.unmount()
    })

    // A one-off "Summarize this recording" scan mints an inline scanner the scanner endpoints refuse to
    // serve, so a back button aimed at it 404s and drops the reader on the vision empty state. Both ways
    // off this page, going back and retrying, must land on the recording instead.
    test.each([
        {
            origin: 'configured' as const,
            destination: '/replay-vision/scanner-9',
            leadsTo: 'the scanner page',
        },
        {
            origin: 'inline' as const,
            destination: '/replay/sess-1',
            leadsTo: 'the recording',
        },
    ])('$origin scanner observations lead back to $leadsTo', async ({ origin, destination }) => {
        scannerOrigin = origin
        const logic = replayObservationLogic({ id: 'obs-1' })
        logic.mount()
        try {
            await expectLogic(logic).toDispatchActions(['loadObservationSuccess'])
            // The scene's back button follows the second-to-last crumb, so that's what "back" means here.
            const { breadcrumbs } = sceneLogic.values
            expect(breadcrumbs[breadcrumbs.length - 2].path).toBe(destination)

            await expectLogic(logic, () => logic.actions.retryObservation()).toDispatchActions([
                'retryObservationSuccess',
            ])
            expect(retrySpy).toHaveBeenCalledTimes(1)
            expect(logic.values.retrying).toBe(false)
            // Staying put would poll a deleted id and toast an error per tick.
            expect(router.values.location.pathname).toContain(destination)
        } finally {
            logic.unmount()
        }
    })

    // The list view rides along in the observation URL, so the back crumb restores the tab, filters,
    // sort, and page the reader opened the observation from rather than the scanner overview.
    it('back returns to the filtered observations list the reader came from', async () => {
        router.actions.push('/replay-vision/observation/obs-1', {
            tab: 'observations',
            verdict: 'yes',
            sort: 'score',
            page: 2,
        })
        const logic = replayObservationLogic({ id: 'obs-1' })
        logic.mount()
        try {
            await expectLogic(logic).toDispatchActions(['loadObservationSuccess'])
            const { breadcrumbs } = sceneLogic.values
            expect(breadcrumbs[breadcrumbs.length - 2].path).toBe(
                '/replay-vision/scanner-9?tab=observations&page=2&sort=score&verdict=yes'
            )
        } finally {
            logic.unmount()
        }
    })

    // The router decodes `q=true` to a boolean, so a naive string-only guard would drop it and land
    // back on an empty search. Searching the literal text "true" must survive the round trip.
    it('preserves a search query the router decoded to a boolean', async () => {
        router.actions.push('/replay-vision/observation/obs-1', { tab: 'search', q: 'true' })
        const logic = replayObservationLogic({ id: 'obs-1' })
        logic.mount()
        try {
            await expectLogic(logic).toDispatchActions(['loadObservationSuccess'])
            const { breadcrumbs } = sceneLogic.values
            expect(breadcrumbs[breadcrumbs.length - 2].path).toBe('/replay-vision/scanner-9?tab=search&q=true')
        } finally {
            logic.unmount()
        }
    })

    // Retry deletes the row and mints a pending replacement with no verdict, so the redirect must
    // drop the reader's filters and page — a filtered list would hide the row it promises "shortly".
    it('retry lands on the unfiltered scanner page, not the reader saved list view', async () => {
        router.actions.push('/replay-vision/observation/obs-1', { tab: 'observations', verdict: 'yes', page: 2 })
        const logic = replayObservationLogic({ id: 'obs-1' })
        logic.mount()
        try {
            await expectLogic(logic).toDispatchActions(['loadObservationSuccess'])
            await expectLogic(logic, () => logic.actions.retryObservation()).toDispatchActions([
                'retryObservationSuccess',
            ])
            expect(router.values.location.pathname).toContain('/replay-vision/scanner-9')
            expect(router.values.searchParams).toEqual({})
        } finally {
            logic.unmount()
        }
    })

    const row = (id: string): ReplayObservationApi =>
        ({
            id,
            scanner_id: 'scanner-9',
            scanner_origin: 'configured',
            session_id: `sess-${id}`,
        }) as ReplayObservationApi
    const page = (ids: string[], overrides: Partial<ObservationsPage> = {}): ObservationsPage => ({
        rows: ids.map(row),
        number: 1,
        pageSize: 3,
        total: ids.length,
        filterParams: {},
        ...overrides,
    })

    it.each([
        ['a row with both neighbors on the page', page(['a', 'b', 'c']), 1, {}, { previous: 'a', next: 'c' }],
        ['the first row of the first page', page(['a', 'b', 'c']), 0, {}, { previous: null, next: 'b' }],
        [
            'the last row of the last page',
            page(['a', 'b', 'c'], { number: 2, total: 6 }),
            2,
            {},
            { previous: 'b', next: null },
        ],
        ['the first row of a later page', page(['a', 'b', 'c'], { number: 2, total: 6 }), 0, {}, null],
        ['the last row of an earlier page', page(['a', 'b', 'c'], { total: 6 }), 2, {}, null],
        ['a page loaded under other filters', page(['a', 'b', 'c']), 1, { verdict: 'yes' }, null],
    ])('resolves prev/next for %s', (_case, handoff, index, params, expected) => {
        expect(neighborsFromPage(handoff, index, params as VisionObservationsRetrieveParams)).toEqual(expected)
    })

    it('paints the row from the table page and skips the filtered read when the page answers prev/next', async () => {
        lastObservationsPage.current = page(['a', 'obs-1', 'c'], {
            filterParams: { verdict: 'yes' } as VisionObservationsRetrieveParams,
        })
        router.actions.push('/replay-vision/observation/obs-1', { verdict: 'yes' })
        const logic = replayObservationLogic({ id: 'obs-1' })
        logic.mount()
        try {
            expect(logic.values.observation?.session_id).toBe('sess-obs-1')
            expect(logic.values.previousObservationId).toBe('a')
            expect(logic.values.nextObservationId).toBe('c')
            await expectLogic(logic).toDispatchActions(['loadObservationSuccess'])
            expect(logic.values.observation?.session_id).toBe('sess-1')
            expect(logic.values.nextObservationId).toBe('c')
            expect(retrieveUrls).toEqual([expect.not.stringContaining('?')])
        } finally {
            logic.unmount()
        }
    })

    it('falls back to the filtered read when the page cannot answer prev/next', async () => {
        router.actions.push('/replay-vision/observation/obs-1', { verdict: 'yes' })
        const logic = replayObservationLogic({ id: 'obs-1' })
        logic.mount()
        try {
            await expectLogic(logic).toDispatchActions(['loadObservationSuccess'])
            expect(logic.values.nextObservationId).toBe('next-from-retrieve')
            expect(retrieveUrls).toEqual([expect.stringContaining('verdict=yes')])
        } finally {
            logic.unmount()
        }
    })

    // A pending or running observation reloads every few seconds. The reload re-enters the loading
    // state, so prev/next must not fall back to a spinner that rejects clicks on every tick.
    it('keeps prev/next clickable while a background reload runs', async () => {
        router.actions.push('/replay-vision/observation/obs-1', { verdict: 'yes' })
        const logic = replayObservationLogic({ id: 'obs-1' })
        logic.mount()
        try {
            await expectLogic(logic).toDispatchActions(['loadObservationSuccess'])
            logic.actions.loadObservation()
            expect(logic.values.observationLoading).toBe(true)
            expect(logic.values.neighborsPending).toBe(false)
            expect(logic.values.previousObservationId).toBe('prev-from-retrieve')
            expect(logic.values.nextObservationId).toBe('next-from-retrieve')
            await waitFor(() => expect(logic.values.observationLoading).toBe(false))
        } finally {
            logic.unmount()
        }
    })

    it('drops the row from the table page and reports the error when its first read fails', async () => {
        retrieveStatus = 500
        lastObservationsPage.current = page(['a', 'obs-1', 'c'])
        router.actions.push('/replay-vision/observation/obs-1')
        const logic = replayObservationLogic({ id: 'obs-1' })
        logic.mount()
        try {
            expect(logic.values.observation?.session_id).toBe('sess-obs-1')
            await expectLogic(logic).toDispatchActions(['loadObservationFailure'])
            expect(logic.values.observation).toBeNull()
            expect(lemonToast.error).toHaveBeenCalledTimes(1)
        } finally {
            logic.unmount()
        }
    })

    it('does not seed from a page once the scene has been left', async () => {
        lastObservationsPage.current = page(['a', 'obs-1', 'c'])
        sceneLogic.unmount()
        sceneLogic.mount()
        router.actions.push('/replay-vision/observation/obs-1')
        const logic = replayObservationLogic({ id: 'obs-1' })
        logic.mount()
        try {
            expect(logic.values.observation).toBeNull()
            await expectLogic(logic).toDispatchActions(['loadObservationSuccess'])
        } finally {
            logic.unmount()
        }
    })
})
