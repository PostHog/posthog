import api from 'lib/api'

import { loadWizardOnboardingStartTime } from './wizardApi'

jest.mock('lib/api', () => ({ __esModule: true, default: { getResponse: jest.fn() } }))

describe('Wizard onboarding server clock', () => {
    afterEach(() => jest.useRealTimers())

    it.each(['ahead', 'behind', 'missing', 'offline'])(
        'uses server time with an %s browser clock or falls back when unavailable',
        async (clock) => {
            jest.useFakeTimers()
            const serverTime = '2026-09-23T10:00:00.000Z'
            const browserTime = Date.parse(serverTime) + (clock === 'behind' ? -60_000 : 60_000)
            jest.setSystemTime(browserTime)
            jest.mocked(api.getResponse).mockImplementationOnce(async () => {
                if (clock === 'offline') {
                    throw new Error('offline')
                }
                return new Response(null, { headers: clock === 'missing' ? {} : { Date: serverTime } })
            })
            expect(await loadWizardOnboardingStartTime('1')).toBe(
                clock === 'missing' || clock === 'offline' ? new Date(browserTime).toISOString() : serverTime
            )
        }
    )
})
