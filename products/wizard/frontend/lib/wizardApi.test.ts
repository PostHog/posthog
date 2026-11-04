import api from 'lib/api'

import { SERVER_CLOCK_TIMEOUT_MS, loadWizardOnboardingStartTime } from './wizardApi'

jest.mock('lib/api', () => ({ __esModule: true, default: { getResponse: jest.fn() } }))

describe('Wizard onboarding server clock', () => {
    afterEach(() => jest.useRealTimers())

    it.each(['ahead', 'behind', 'missing', 'offline', 'stalled'])(
        'uses server time with an %s browser clock or falls back when unavailable',
        async (clock) => {
            jest.useFakeTimers()
            const serverTime = '2026-09-23T10:00:00.000Z'
            const browserTime = Date.parse(serverTime) + (clock === 'behind' ? -60_000 : 60_000)
            jest.setSystemTime(browserTime)
            jest.mocked(api.getResponse).mockImplementationOnce(async (_url, options) => {
                if (clock === 'offline') {
                    throw new Error('offline')
                }
                if (clock === 'stalled') {
                    return await new Promise<Response>((_resolve, reject) =>
                        options?.signal?.addEventListener('abort', () => reject(new Error('aborted')))
                    )
                }
                return new Response(null, { headers: clock === 'missing' ? {} : { Date: serverTime } })
            })
            const startTime = loadWizardOnboardingStartTime('1')
            await jest.advanceTimersByTimeAsync(SERVER_CLOCK_TIMEOUT_MS)
            expect(await startTime).toBe(
                clock === 'ahead' || clock === 'behind' ? serverTime : new Date(browserTime).toISOString()
            )
        }
    )
})
