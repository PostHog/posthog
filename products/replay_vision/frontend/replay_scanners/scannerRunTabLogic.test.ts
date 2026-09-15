import { expectLogic } from 'kea-test-utils'

import { lemonToast } from 'lib/lemon-ui/LemonToast'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { visionQuotaLogic } from '../logics/visionQuotaLogic'
import { makeQuota } from '../utils/quotaTestUtils'
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
                                {
                                    id: 'obs-3',
                                    session_id: 's3',
                                    status: 'ineligible',
                                    error_reason: 'too_short:Only 5.0s long; min is 15s',
                                },
                            ],
                            count: 4,
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

    it('keeps the newest observation per session and leaves retry headroom above the visible-row count', async () => {
        await expectLogic(logic, () => logic.actions.setVisibleSessionIds(['s1', 's2', 's3'])).toDispatchActions([
            'loadObservationsSuccess',
        ])

        // A retried session shows its fresh running observation, not the stale failed one the API lists after it.
        // An ineligible row keeps its reason, which is what the status tag needs to explain the skip on hover.
        expect(logic.values.observationBySession).toEqual({
            s1: { id: 'obs-retry', status: 'running', errorReason: null },
            s2: { id: 'obs-2', status: 'succeeded', errorReason: null },
            s3: {
                id: 'obs-3',
                status: 'ineligible',
                errorReason: 'too_short:Only 5.0s long; min is 15s',
            },
        })
        // The connected replayScannerLogic fires its own paged list load; ours is the session_id lookup.
        const lookupUrl = requestedUrls.find((url) => url.includes('session_id='))
        expect(lookupUrl).not.toBeUndefined()
        // On the server's default page size the tail is dropped and those sessions render "Not scanned";
        // one-per-row would drop them as soon as a retry stacks a second observation onto a session.
        expect(lookupUrl).toContain('limit=12')
    })

    it('releases the pending bridge once the scanned session lands in the lookup', async () => {
        await expectLogic(logic, () => {
            logic.actions.setPendingId('s1')
            logic.actions.setVisibleSessionIds(['s1', 's2'])
        }).toDispatchActions(['loadObservationsSuccess'])
        expect(logic.values.pendingId).toBeNull()
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

    it('splits a selection above the per-request cap into cap-sized batches', async () => {
        const postedBatches: string[][] = []
        useMocks({
            post: {
                '/api/projects/:team/vision/scanners/:id/bulk_observe/': async ({ request }: { request: Request }) => {
                    const body = await request.json()
                    postedBatches.push(body.session_ids)
                    return [
                        202,
                        {
                            started: body.session_ids.length,
                            results: body.session_ids.map((session_id: string) => ({
                                session_id,
                                scan_outcome: 'started',
                            })),
                        },
                    ]
                },
            },
        })
        const sessionIds = Array.from({ length: 250 }, (_, i) => `s${i}`)

        await expectLogic(logic, () => logic.actions.startBulkScan(sessionIds)).toFinishAllListeners()

        // One request of 250 is rejected whole by the API, so every session has to go in a batch it accepts.
        expect(postedBatches.map((batch) => batch.length)).toEqual([200, 50])
        expect(postedBatches.flat()).toEqual(sessionIds)
    })

    it('stops batching once a batch reports a skip', async () => {
        const postedBatches: string[][] = []
        useMocks({
            post: {
                '/api/projects/:team/vision/scanners/:id/bulk_observe/': async ({ request }: { request: Request }) => {
                    const body = await request.json()
                    postedBatches.push(body.session_ids)
                    return [
                        202,
                        {
                            started: 0,
                            results: body.session_ids.map((session_id: string) => ({
                                session_id,
                                scan_outcome: 'skipped_quota',
                            })),
                        },
                    ]
                },
            },
        })

        await expectLogic(logic, () =>
            logic.actions.startBulkScan(Array.from({ length: 250 }, (_, i) => `s${i}`))
        ).toFinishAllListeners()

        // The quota that bound on the first batch binds on every later one, so asking again only burns requests.
        expect(postedBatches).toHaveLength(1)
    })

    // A zero-start run has to name every outcome it produced. Dropping one tells the user to retry
    // a selection that is already answered, or hides the failures behind a skip message.
    test.each([
        ['every session resolved', ['already_scanned', 'already_running'], 'info', ['Nothing new to scan']],
        [
            'resolved alongside a failure',
            ['already_scanned', 'failed'],
            'warning',
            ['1 already scanned', '1 failed to start'],
        ],
        [
            'resolved alongside a skip',
            ['already_scanned', 'skipped_quota'],
            'warning',
            ['credit limit', '1 already scanned'],
        ],
    ])('names every outcome when nothing started: %s', async (_name, outcomes, level, fragments) => {
        const errorToast = jest.spyOn(lemonToast, 'error').mockImplementation(() => 'toast-id')
        const toast = jest.spyOn(lemonToast, level as 'info' | 'warning').mockImplementation(() => 'toast-id')
        useMocks({
            post: {
                '/api/projects/:team/vision/scanners/:id/bulk_observe/': () => [
                    202,
                    {
                        started: 0,
                        results: outcomes.map((scan_outcome, i) => ({ session_id: `s${i}`, scan_outcome })),
                    },
                ],
            },
        })

        await expectLogic(logic, () =>
            logic.actions.startBulkScan(outcomes.map((_, i) => `s${i}`))
        ).toFinishAllListeners()

        // The scanner load in the mounted logic toasts its own error here, so match the message
        // rather than the call count.
        expect(errorToast).not.toHaveBeenCalledWith(expect.stringContaining('Please try again'))
        const message = toast.mock.calls[0][0]
        for (const fragment of fragments) {
            expect(message).toContain(fragment)
        }
        errorToast.mockRestore()
        toast.mockRestore()
    })

    it('keeps polling after a bulk scan whose refetch beats the new observation rows', async () => {
        // toFinishAllListeners hangs under fake timers (msw resolves responses on the clock),
        // so the whole test advances fake time instead, which also flushes microtasks.
        jest.useFakeTimers()
        try {
            let lookups = 0
            useMocks({
                get: {
                    '/api/projects/:team/vision/scanners/:id/observations/': ({ request }: { request: Request }) => {
                        if (request.url.includes('session_id=')) {
                            lookups += 1
                        }
                        // A bulk trigger only starts the workflows; the rows are written by their
                        // first activity, so the refetch right after it can still see nothing.
                        return [200, { results: [], count: 0 }]
                    },
                },
                post: {
                    '/api/projects/:team/vision/scanners/:id/bulk_observe/': () => [
                        202,
                        { started: 1, results: [{ session_id: 's9', scan_outcome: 'started' }] },
                    ],
                },
            })

            logic.actions.setVisibleSessionIds(['s9'])
            logic.actions.startBulkScan(['s9'])
            await jest.advanceTimersByTimeAsync(1_000)
            const afterScan = lookups
            expect(afterScan).toBeGreaterThan(0)

            await jest.advanceTimersByTimeAsync(3_000)
            // Nothing is in progress and no row landed, so without a grace window the timer is
            // disposed here and the started rows read "Not scanned" until the scene reloads.
            expect(lookups).toBeGreaterThan(afterScan)
        } finally {
            jest.useRealTimers()
        }
    })

    it('refreshes the credit total after a bulk run starts scans', async () => {
        let quotaLoads = 0
        useMocks({
            get: {
                '/api/projects/:team/vision/quota/': () => {
                    quotaLoads += 1
                    return [200, makeQuota()]
                },
            },
            post: {
                '/api/projects/:team/vision/scanners/:id/bulk_observe/': () => [
                    202,
                    { started: 1, results: [{ session_id: 's1', scan_outcome: 'started' }] },
                ],
            },
        })
        const quotaLogic = visionQuotaLogic()
        quotaLogic.mount()
        await expectLogic(quotaLogic).toFinishAllListeners()
        const loadsOnMount = quotaLoads

        await expectLogic(logic, () => logic.actions.startBulkScan(['s1'])).toFinishAllListeners()
        await expectLogic(quotaLogic).toFinishAllListeners()

        // Every started scan reserves credits at once, so without this the credit banner on the scanner
        // page keeps showing pre-scan usage until the scene remounts.
        expect(quotaLoads).toBe(loadsOnMount + 1)
        quotaLogic.unmount()
    })
})
