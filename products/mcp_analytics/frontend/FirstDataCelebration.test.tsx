import { render } from '@testing-library/react'
import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import api from 'lib/api'

import { initKeaTests } from '~/test/init'

import { FirstDataCelebration } from './FirstDataCelebration'
import { mcpAnalyticsOnboardingLogic } from './mcpAnalyticsOnboardingLogic'

jest.mock('lib/api')

const mockApi = api as jest.Mocked<typeof api>

// Signal row shape: [has_initialize, tool_calls_total, tool_calls_7d, first_call_at]
const CONNECTED = [1, 0, 0, '1970-01-01T00:00:00Z']
const ONE_CALL = [1, 1, 1, '2026-07-01T00:00:00Z']

describe('FirstDataCelebration', () => {
    beforeEach(() => {
        initKeaTests()
    })

    afterEach(() => {
        jest.restoreAllMocks()
    })

    it.each([
        { reducedMotion: false, animated: true },
        { reducedMotion: true, animated: false },
    ])('settles the arrival and captures animated=$animated with reduced motion $reducedMotion', async (testCase) => {
        jest.spyOn(window, 'matchMedia').mockImplementation(
            (query: string) =>
                ({ matches: testCase.reducedMotion && query === '(prefers-reduced-motion: reduce)' }) as MediaQueryList
        )
        const capture = jest.spyOn(posthog, 'capture').mockImplementation(() => undefined)
        jest.spyOn(mockApi, 'query')
            .mockReset()
            .mockResolvedValueOnce({ results: [CONNECTED] } as any)
            .mockResolvedValueOnce({ results: [ONE_CALL] } as any)
        const logic = mcpAnalyticsOnboardingLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        logic.actions.loadSignals()
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.firstDataWatch).toBe('arrived')

        render(<FirstDataCelebration />)

        expect(logic.values.firstDataWatch).toBe('settled')
        expect(capture).toHaveBeenCalledWith(
            'mcp analytics first data seen live',
            expect.objectContaining({ animated: testCase.animated }),
            undefined
        )
    })
})
