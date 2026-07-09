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
            post: {
                '/api/projects/:team/vision/scanners/:id/observe/': () => [202, {}],
            },
            get: {
                '/api/projects/:team/vision/scanners/:id/': () => [404, {}],
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

    it('releases the pending bridge once the scanned session lands in the lookup', async () => {
        await expectLogic(logic, () => {
            logic.actions.markPending('s1')
            logic.actions.setVisibleSessionIds(['s1', 's2'])
        }).toDispatchActions(['loadObservationsSuccess'])
        expect(logic.values.pendingSessionIds).toEqual({})
    })

    it('scans multiple rows concurrently instead of blocking on the first pending session', () => {
        // Regression: the single-scalar gate made every row but the first a silent no-op while one scan was pending.
        logic.actions.startScan('s1')
        logic.actions.startScan('s2')
        expect(logic.values.pendingSessionIds).toEqual({ s1: true, s2: true })
    })

    it('leaves an unrelated pending session untouched when another one lands', async () => {
        // A stuck lookup on one session must not freeze the rest of the table.
        await expectLogic(logic, () => {
            logic.actions.markPending('s1')
            logic.actions.markPending('missing')
            logic.actions.setVisibleSessionIds(['s1', 's2'])
        }).toDispatchActions(['loadObservationsSuccess'])
        // s1 landed in the lookup and cleared; 'missing' never appears, so its bridge stays up.
        expect(logic.values.pendingSessionIds).toEqual({ missing: true })
    })
})
