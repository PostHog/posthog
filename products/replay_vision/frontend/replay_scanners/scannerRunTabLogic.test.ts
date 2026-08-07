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

    it('select all matching resolves filters to unscanned sessions, excluding already-scanned rows', async () => {
        useMocks({
            get: {
                '/api/environments/:team/session_recordings': () => [
                    200,
                    { results: [{ id: 's1' }, { id: 's2' }, { id: 's3' }, { id: 's4' }, { id: 's5' }], has_next: true },
                ],
            },
        })
        // Load observations so s1–s3 read as scanned, matching the per-row selectable gate the affordance mirrors.
        await expectLogic(logic, () => logic.actions.setVisibleSessionIds(['s1', 's2', 's3'])).toDispatchActions([
            'loadObservationsSuccess',
        ])
        await expectLogic(logic, () => logic.actions.selectAllMatching({} as any)).toDispatchActions([
            'selectAllMatchingSuccess',
        ])
        // Only the unscanned matches are handed to the table's selection — scanned sessions would be a backend no-op.
        expect(logic.values.resolvedSelection).toEqual({ sessionIds: ['s4', 's5'] })
    })
})
