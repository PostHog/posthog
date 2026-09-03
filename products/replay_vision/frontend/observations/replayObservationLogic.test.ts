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
})
