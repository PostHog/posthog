import { expectLogic } from 'kea-test-utils'

import api from 'lib/api'
import { ApiError } from 'lib/api-error'

import { initKeaTests } from '~/test/init'

import { batchSpikeEventsLogic } from './batchSpikeEventsLogic'

describe('batchSpikeEventsLogic', () => {
    let logic: ReturnType<typeof batchSpikeEventsLogic.build>

    const spikeEvent = (issueId: string): any => ({
        id: `spike-${issueId}`,
        issue: { id: issueId },
        detected_at: '2024-01-01T00:00:00Z',
    })

    beforeEach(() => {
        jest.useFakeTimers()
        initKeaTests()
        logic = batchSpikeEventsLogic()
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
        jest.restoreAllMocks()
        jest.useRealTimers()
    })

    // A failed request degrades to no markers, which writes the same value a successful request
    // writes. The issues list reloads spike events on every completed list query, so without a
    // supersede check an older request's late failure clears the markers a newer one just wrote.
    it('does not let a superseded failing request clear newer spike events', async () => {
        let rejectFirstRequest: (error: unknown) => void = () => {}
        const firstRequest = new Promise((_, reject) => {
            rejectFirstRequest = reject
        })
        jest.spyOn(api.errorTracking, 'getSpikeEvents')
            .mockReturnValueOnce(firstRequest as any)
            .mockResolvedValueOnce({ results: [spikeEvent('issue-2')] } as any)

        logic.actions.loadSpikeEventsForIssues(['issue-1'])
        await jest.advanceTimersByTimeAsync(100)

        logic.actions.loadSpikeEventsForIssues(['issue-2'])
        await jest.advanceTimersByTimeAsync(100)
        await expectLogic(logic).toDispatchActions(['loadSpikeEventsForIssuesSuccess'])
        expect(logic.values.spikeEventsByIssueId).toEqual({ 'issue-2': [spikeEvent('issue-2')] })

        rejectFirstRequest(new ApiError('Service Unavailable', 503))
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.spikeEventsByIssueId).toEqual({ 'issue-2': [spikeEvent('issue-2')] })
    })
})
