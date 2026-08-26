import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { replayObservationLogic } from './replayObservationLogic'
import { replayObservationSceneLogic } from './replayObservationSceneLogic'

describe('replayObservationLogic', () => {
    let retrySpy: jest.Mock
    let scannerOrigin: 'configured' | 'inline'
    let sceneLogic: ReturnType<typeof replayObservationSceneLogic.build>

    beforeEach(() => {
        scannerOrigin = 'configured'
        retrySpy = jest.fn(() => [202, { workflow_id: 'wf-retry' }])
        useMocks({
            get: {
                '/api/projects/:team/vision/observations/:id/': () => [
                    200,
                    {
                        id: 'obs-1',
                        scanner_id: 'scanner-9',
                        scanner_origin: scannerOrigin,
                        session_id: 'sess-1',
                        status: 'failed',
                        error_reason: 'internal_error:boom',
                        scanner_snapshot: {
                            // Inline scanners are unnamed, which is why their crumb read "Scanner" before it 404'd.
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
                        created_at: '2026-07-01T00:00:00Z',
                    },
                ],
            },
            post: {
                '/api/projects/:team/vision/observations/:id/retry/': retrySpy,
            },
        })
        initKeaTests()
        sceneLogic = replayObservationSceneLogic()
        sceneLogic.mount()
    })

    afterEach(() => {
        sceneLogic?.unmount()
    })

    // A one-off "Summarize this recording" scan mints an inline scanner, and the scanner endpoints refuse
    // to serve it. Linking to one anyway 404s and drops the reader on the vision empty state, so both the
    // breadcrumb and the post-retry hand-off must point at the recording instead.
    test.each([
        {
            origin: 'configured' as const,
            crumbScannerId: 'scanner-9',
            destination: '/replay-vision/scanner-9',
            leadsTo: 'the scanner page',
        },
        {
            origin: 'inline' as const,
            crumbScannerId: null,
            destination: '/replay/sess-1',
            leadsTo: 'the recording',
        },
    ])('$origin scanner observations lead to $leadsTo', async ({ origin, crumbScannerId, destination }) => {
        scannerOrigin = origin
        const logic = replayObservationLogic({ id: 'obs-1' })
        logic.mount()
        try {
            await expectLogic(logic).toDispatchActions(['loadObservationSuccess'])
            expect(sceneLogic.values.scannerContext.scannerId).toBe(crumbScannerId)

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
})
