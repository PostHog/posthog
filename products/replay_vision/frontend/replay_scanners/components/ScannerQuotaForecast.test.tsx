import '@testing-library/jest-dom'

import { render, screen } from '@testing-library/react'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { visionQuotaLogic } from '../../logics/visionQuotaLogic'
import { replayScannerLogic } from '../replayScannerLogic'
import { ScannerQuotaForecast } from './ScannerQuotaForecast'

const QUOTA = {
    credit_limit: 10000,
    credits_used: 2000,
    credits_settled: 2000,
    credits_reserved: 0,
    remaining: 8000,
    exhausted: false,
    period_start: '2026-05-01T00:00:00Z',
    period_end: '2026-06-01T00:00:00Z',
    projected_monthly_credits: 3000,
    free_credits_used: 0,
}

const ESTIMATE = {
    matched_sessions_in_window: 1840,
    window_days: 30,
    estimated_observations_per_month: 92,
    credits_per_observation: 1,
    estimated_credits_per_month: 92,
    other_enabled_scanners_monthly_credits: 2900,
    active_backfill_credits: 0,
    sampling_rate: 0.05,
}

describe('ScannerQuotaForecast', () => {
    let logic: ReturnType<typeof replayScannerLogic.build>

    beforeEach(() => {
        useMocks({
            get: {
                '/api/projects/:team/vision/scanners/:id/': () => [404, {}],
                '/api/projects/:team/vision/quota/': QUOTA,
            },
        })
        localStorage.clear()
        initKeaTests()
        visionQuotaLogic.mount()
        logic = replayScannerLogic({ id: 'new' })
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
        visionQuotaLogic.unmount()
    })

    it('points the spend limit caption at the billing page for Replay Vision', async () => {
        visionQuotaLogic.actions.loadQuotaSuccess(QUOTA as never)
        logic.actions.loadScannerEstimateSuccess(ESTIMATE)

        render(<ScannerQuotaForecast scannerId="new" />)

        const caption = await screen.findByText(/^Spend limit ·/)

        expect(caption.tagName).toBe('A')
        expect(caption).toHaveAttribute('href', '/organization/billing?products=replay_vision')
    })
})
