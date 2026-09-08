import '@testing-library/jest-dom'

import { render, screen } from '@testing-library/react'

import type { ProactiveHistoryEntryApi } from 'products/subscriptions/frontend/generated/api.schemas'

import { SubscriptionPulseHistory } from './SubscriptionPulseHistory'

const history: ProactiveHistoryEntryApi[] = [
    {
        delivery_id: '019fd71b-1df8-0000-6b5f-2c35bb4aacc2',
        recommendation_title: 'Reduce sign-up friction',
        why_now: 'New users are leaving before they complete account setup.',
        citations: [{ title: 'Sign-up trend', url: 'https://example.com/sign-up-trend' }],
        artifact: {
            kind: 'draft_pr',
            status: 'adopted',
            url: 'https://example.com/draft-pr',
            prepared_at: '2026-09-08T09:00:00Z',
            adopted_at: '2026-09-09T09:00:00Z',
        },
        outcome: {
            status: 'improved',
            metric_name: 'Completed sign-ups',
            expected_metric_movement: 'completed sign-ups',
            direction: 'increase',
            baseline_value: '120.0000000000',
            observed_value: '146.5000000000',
            delta: '26.5000000000',
            baseline_from: '2026-09-01',
            baseline_to: '2026-09-07',
            observed_from: '2026-09-09T00:00:00Z',
            observed_to: '2026-09-15T23:59:59.999999Z',
            due_at: '2026-09-16T09:00:00Z',
        },
    },
]

describe('SubscriptionPulseHistory', () => {
    it('shows prepared and adopted artifact timing with a concise absolute outcome', () => {
        render(<SubscriptionPulseHistory history={history} loading={false} hasError={false} />)

        expect(screen.getByText('Prepared')).toBeInTheDocument()
        expect(screen.getAllByText('Adopted')).toHaveLength(2)
        expect(screen.getByText(/Baseline 120, observed 146\.5, delta 26\.5/)).toBeInTheDocument()
        expect(screen.getByText(/Expected: Increase completed sign-ups/)).toBeInTheDocument()
        expect(screen.getByText(/Baseline window: 2026-09-01 to 2026-09-07/)).toBeInTheDocument()
    })

    it.each<[string, ProactiveHistoryEntryApi[] | null, boolean, boolean, string]>([
        ['loading', null, true, false, 'subscription-pulse-history-loading'],
        ['error', null, false, true, 'Could not load follow-up recommendations. Refresh the page and try again.'],
        ['empty', [], false, false, 'No follow-up recommendations yet.'],
    ])('shows the %s state', (_name, stateHistory, loading, hasError, expectedText) => {
        const { container } = render(
            <SubscriptionPulseHistory history={stateHistory} loading={loading} hasError={hasError} />
        )

        if (_name === 'loading') {
            expect(container.querySelector('[data-attr="subscription-pulse-history-loading"]')).toBeInTheDocument()
        } else {
            expect(screen.getByText(expectedText)).toBeInTheDocument()
        }
    })
})
