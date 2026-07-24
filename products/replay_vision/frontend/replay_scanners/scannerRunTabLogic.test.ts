import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { scannerRunTabLogic } from './scannerRunTabLogic'

describe('scannerRunTabLogic', () => {
    let logic: ReturnType<typeof scannerRunTabLogic.build>
    let requestedUrls: string[]

    beforeEach(() => {
        requestedUrls = []
        useMocks({
            get: {
                '/api/projects/:team/vision/scanners/:id/': () => [404, {}],
                // The connected replayScannerLogic loads stats on mount; give it a valid shape so its
                // status-counts selector doesn't throw when this test awaits the full listener cascade.
                '/api/projects/:team/vision/scanners/:id/observations/stats/': () => [
                    200,
                    { status_counts: { in_flight: 0, succeeded: 0, failed: 0, ineligible: 0 }, total: 0 },
                ],
                '/api/projects/:team/vision/scanners/:id/observations/': ({ request }: { request: Request }) => {
                    requestedUrls.push(request.url)
                    return [
                        200,
                        {
                            // Newest-first, mirroring the API's -created_at default ordering.
                            results: [
                                { id: 'obs-retry', session_id: 's1', status: 'running' },
                                { id: 'obs-original', session_id: 's1', status: 'failed' },
                                { id: 'obs-2', session_id: 's2', status: 'succeeded' },
                            ],
                            count: 3,
                        },
                    ]
                },
            },
        })
        initKeaTests()
        logic = scannerRunTabLogic({ scannerId: 'scanner-1' })
        logic.mount()
    })

    afterEach(() => {
        logic?.unmount()
    })

    it('keeps the newest observation per session and does not cap the page to the visible-row count', async () => {
        await expectLogic(logic, () => logic.actions.setVisibleSessionIds(['s1', 's2'])).toDispatchActions([
            'loadObservationsSuccess',
        ])

        // A retried session shows its fresh running observation, not the stale failed one the API lists after it.
        expect(logic.values.observationBySession).toEqual({
            s1: { id: 'obs-retry', status: 'running' },
            s2: { id: 'obs-2', status: 'succeeded' },
        })
        // The connected replayScannerLogic fires its own paged list load; ours is the session_id lookup.
        const lookupUrl = requestedUrls.find((url) => url.includes('session_id='))
        expect(lookupUrl).not.toBeUndefined()
        expect(lookupUrl).not.toContain('limit=')
    })

    it('registers a pending scan per row so rapid clicks on different rows all take', async () => {
        const posted: string[] = []
        useMocks({
            post: {
                '/api/projects/:team/vision/scanners/:id/observe/': async ({ request }: { request: Request }) => {
                    posted.push((await request.json()).session_id)
                    return [202, {}]
                },
            },
        })
        // No visible rows loaded, so the post-scan refetch is a no-op and the pending bridge stays put.
        await expectLogic(logic, () => {
            logic.actions.startScan('a')
            logic.actions.startScan('b')
        }).toFinishAllListeners()

        // Both clicks post and hold their own spinner — neither is swallowed by the other being in flight.
        expect(posted.sort()).toEqual(['a', 'b'])
        expect(logic.values.pendingSessionIds).toEqual({ a: true, b: true })
    })

    it('releases a row from pending once its observation lands in the lookup', async () => {
        useMocks({
            post: {
                '/api/projects/:team/vision/scanners/:id/observe/': () => [202, {}],
            },
        })
        await expectLogic(logic, () => logic.actions.startScan('s1')).toFinishAllListeners()
        expect(logic.values.pendingSessionIds).toEqual({ s1: true })

        logic.actions.loadObservationsSuccess({ s1: { id: 'obs-1', status: 'succeeded' } })
        expect(logic.values.pendingSessionIds).toEqual({})
    })

    it('releases a row from pending when the scan fails to start', async () => {
        useMocks({
            post: {
                '/api/projects/:team/vision/scanners/:id/observe/': () => [500, { detail: 'boom' }],
            },
        })
        // A failed post must not strand the row's spinner spinning forever.
        await expectLogic(logic, () => logic.actions.startScan('s1')).toFinishAllListeners()
        expect(logic.values.pendingSessionIds).toEqual({})
    })

    it('bulk scan posts the selected sessions and clears its loading state', async () => {
        let postedBody: any
        useMocks({
            post: {
                '/api/projects/:team/vision/scanners/:id/bulk_observe/': async ({ request }: { request: Request }) => {
                    postedBody = await request.json()
                    return [
                        202,
                        {
                            started: 2,
                            results: [
                                { session_id: 'a', scan_outcome: 'started' },
                                { session_id: 'b', scan_outcome: 'started' },
                                { session_id: 'c', scan_outcome: 'skipped_limit' },
                            ],
                        },
                    ]
                },
            },
        })
        await expectLogic(logic, () => logic.actions.startBulkScan(['a', 'b', 'c'])).toFinishAllListeners()
        // The selected session ids reach the bulk endpoint, and the button's loading state is released.
        expect(postedBody).toEqual({ session_ids: ['a', 'b', 'c'] })
        expect(logic.values.bulkScanning).toBe(false)
    })
})
