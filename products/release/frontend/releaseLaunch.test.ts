import { scheduledChangesCreate } from 'products/feature_flags/frontend/generated/api'

import { defaultLaunchFlagIds, scheduleFlagLaunches } from './releaseLaunch'

jest.mock('products/feature_flags/frontend/generated/api', () => ({
    scheduledChangesCreate: jest.fn(),
}))

const mockedCreate = jest.mocked(scheduledChangesCreate)

describe('releaseLaunch', () => {
    beforeEach(() => {
        mockedCreate.mockReset()
    })

    it('selects only the flags that are off by default', () => {
        expect(
            defaultLaunchFlagIds([
                { id: 1, key: 'on-flag', active: true },
                { id: 2, key: 'off-flag', active: false },
                { id: 3, key: 'other-off-flag', active: false },
            ])
        ).toEqual([2, 3])
    })

    it('schedules each flag to turn on at the shared time and reports the ones that failed', async () => {
        mockedCreate.mockImplementation(async (_, body) => {
            if (body.record_id === '2') {
                throw new Error('Forbidden')
            }
            return body as never
        })

        const result = await scheduleFlagLaunches('7', [1, 2, 3], '2026-12-01T09:00:00.000Z')

        expect(mockedCreate.mock.calls.map(([projectId, body]) => [projectId, body])).toEqual(
            [1, 2, 3].map((id) => [
                '7',
                {
                    record_id: String(id),
                    model_name: 'FeatureFlag',
                    payload: { operation: 'update_status', value: true },
                    scheduled_at: '2026-12-01T09:00:00.000Z',
                    is_recurring: false,
                },
            ])
        )
        expect(result).toEqual({ scheduledFlagIds: [1, 3], failedFlagIds: [2] })
    })
})
