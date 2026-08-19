import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import type { BackfillEstimateResponseApi, VisionQuotaApi } from '../../generated/api.schemas'
import { BackfillCostEstimate } from './BackfillCostEstimate'

const UNCAPPED_QUOTA = {
    credit_limit: null,
    credits_used: 0,
    remaining: null,
    exhausted: false,
    period_start: '2026-08-01T00:00:00Z',
    period_end: '2026-09-01T00:00:00Z',
    projected_monthly_credits: 0,
    scanners_monthly_credits: 0,
    backfills_committed_credits: 0,
    free_monthly_credits: 0,
} as VisionQuotaApi

const ESTIMATE: BackfillEstimateResponseApi = {
    total_sessions: 40,
    total_credits: 400,
    credits_per_observation: 10,
    credits_remaining: null,
    window_start: '2026-01-01T00:00:00Z',
    window_end: '2026-02-01T00:00:00Z',
}

describe('BackfillCostEstimate', () => {
    beforeEach(() => {
        useMocks({
            get: {
                '/api/projects/:team/vision/quota/': UNCAPPED_QUOTA,
                '/api/billing/': {},
            },
        })
        initKeaTests()
    })

    it('keeps the last estimate and offers a retry when the request failed', async () => {
        const onRetry = jest.fn()
        render(
            <BackfillCostEstimate
                estimate={ESTIMATE}
                loading={false}
                error="The scanner is busy. Wait a moment, then retry."
                onRetry={onRetry}
            />
        )

        // getByText throws if absent, so these two lines assert the card shows the kept estimate
        // rather than blanking to "Pick a time range", and surfaces the failure inline.
        screen.getByText(/at most/)
        screen.getByText('The scanner is busy. Wait a moment, then retry.')
        expect(screen.queryByText('Pick a time range to see the cost')).toBeNull()

        // The inline retry means the user never re-picks the date range to recover. The banner renders
        // responsive duplicate buttons, so click the first.
        await userEvent.click(screen.getAllByRole('button', { name: 'Retry' })[0])
        await waitFor(() => expect(onRetry).toHaveBeenCalledTimes(1))
    })
})
