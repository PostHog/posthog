import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { replayObservationLogic } from './replayObservationLogic'
import { replayObservationSceneLogic } from './replayObservationSceneLogic'

describe('replayObservationLogic', () => {
    let retrySpy: jest.Mock
    let sceneLogic: ReturnType<typeof replayObservationSceneLogic.build>

    beforeEach(() => {
        retrySpy = jest.fn(() => [202, { workflow_id: 'wf-retry' }])
        useMocks({
            get: {
                '/api/projects/:team/vision/observations/:id/': {
                    id: 'obs-1',
                    scanner_id: 'scanner-9',
                    session_id: 'sess-1',
                    status: 'failed',
                    error_reason: 'internal_error:boom',
                    scanner_snapshot: {
                        name: 'My scanner',
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

    it('retry hands off to the scanner page because the retried row is deleted', async () => {
        const logic = replayObservationLogic({ id: 'obs-1' })
        logic.mount()
        try {
            await expectLogic(logic).toDispatchActions(['loadObservationSuccess'])
            await expectLogic(logic, () => logic.actions.retryObservation()).toDispatchActions([
                'retryObservationSuccess',
            ])
            expect(retrySpy).toHaveBeenCalledTimes(1)
            expect(logic.values.retrying).toBe(false)
            // Staying put would poll a deleted id and toast an error per tick.
            expect(router.values.location.pathname).toContain('/replay-vision/scanner-9')
        } finally {
            logic.unmount()
        }
    })
})
