import { dayjs } from 'lib/dayjs'

import { scheduledChangesCreate } from 'products/feature_flags/frontend/generated/api'

import { defaultLaunchFlagIds, isLaunchInPast, scheduleFlagLaunches } from './releaseLaunch'

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
                throw Object.assign(new Error('Conflict'), {
                    status: 409,
                    code: 'change_request_pending',
                    detail: 'A change for this feature flag is already awaiting approval.',
                })
            }
            if (body.record_id === '3') {
                throw Object.assign(new Error('Forbidden'), { status: 403, detail: 'You do not have permission.' })
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
        expect(result).toEqual({
            scheduledFlagIds: [1],
            failures: [
                {
                    flagId: 2,
                    reason: 'A change for this feature flag is already awaiting approval.',
                    pendingApproval: true,
                },
                { flagId: 3, reason: 'You do not have permission.', pendingApproval: false },
            ],
        })
    })

    it.each([
        ['an hour ago in the project time zone', '2026-12-01 08:00', true],
        ['the current minute', '2026-12-01 09:00', true],
        ['an hour from now in the project time zone', '2026-12-01 10:00', false],
    ])('checks a launch at %s', (_, local, past) => {
        const now = dayjs.tz('2026-12-01 09:00', 'America/New_York')
        expect(isLaunchInPast(dayjs(local), 'America/New_York', now)).toBe(past)
    })
})
