import api from 'lib/api'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import {
    DETECTIONS_POLL_INTERVAL_MS,
    RepositoryDetection,
    sourceMapsCloudSetupLogic,
} from './sourceMapsCloudSetupLogic'

const detection = (overrides: Partial<RepositoryDetection> = {}): RepositoryDetection => ({
    repository: 'acme/app',
    kind: 'error-tracking-source-maps',
    task_run_id: 'run-1',
    task_run_status: 'in_progress',
    report: null,
    error: null,
    updated_at: '2026-08-11T00:00:00Z',
    ...overrides,
})

describe('sourceMapsCloudSetupLogic', () => {
    let logic: ReturnType<typeof sourceMapsCloudSetupLogic.build>
    let getSpy: jest.SpyInstance

    const wizardCalls = (): number =>
        getSpy.mock.calls.filter(([url]) => String(url).includes('api/wizard/repository_detections')).length

    beforeEach(() => {
        jest.useFakeTimers()
        useMocks({ get: { '/api/environments/:team_id/integrations': { results: [] } } })
        initKeaTests()
        getSpy = jest.spyOn(api, 'get').mockResolvedValue([])
        logic = sourceMapsCloudSetupLogic()
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
        jest.useRealTimers()
        jest.restoreAllMocks()
    })

    it('re-arms polling after a failed poll while a scan is live', async () => {
        logic.actions.loadDetectionsSuccess([detection()])

        getSpy.mockRejectedValueOnce(new Error('network down'))
        await jest.advanceTimersByTimeAsync(DETECTIONS_POLL_INTERVAL_MS)
        const callsAfterFailure = wizardCalls()

        await jest.advanceTimersByTimeAsync(DETECTIONS_POLL_INTERVAL_MS)
        expect(wizardCalls()).toBe(callsAfterFailure + 1)
    })

    it('does not poll after a failure when no scan is live', async () => {
        logic.actions.loadDetectionsSuccess([detection({ task_run_status: 'completed' })])
        logic.actions.loadDetectionsFailure('network down')

        const callsBefore = wizardCalls()
        await jest.advanceTimersByTimeAsync(DETECTIONS_POLL_INTERVAL_MS * 5)
        expect(wizardCalls()).toBe(callsBefore)
    })
})
