import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'

import {
    marketingAnalyticsLogic,
    MarketingAnalyticsTab,
    SetupSection,
} from 'scenes/web-analytics/tabs/marketing-analytics/frontend/logic/marketingAnalyticsLogic'
import { setupPlanLogic } from 'scenes/web-analytics/tabs/marketing-analytics/frontend/logic/setupPlanLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { NewMarketingAnalyticsDashboard } from './NewMarketingAnalyticsDashboard'

jest.mock('scenes/web-analytics/tiles/WebAnalyticsTile', () => ({ webAnalyticsDataTableQueryContext: {} }))
jest.mock('~/queries/Query/Query', () => ({ Query: () => null }))
jest.mock('scenes/web-analytics/tabs/marketing-analytics/frontend/components/AttributionTab/AttributionTable', () => ({
    AttributionTable: () => null,
}))
jest.mock('scenes/web-analytics/tabs/marketing-analytics/frontend/components/AttributionTab/AttributionTab', () => ({
    AttributionTab: () => null,
}))

describe('Dashboard goal suggestions', () => {
    it('reuses goal suggestions, remembers collapse and opens their review in Setup', async () => {
        useMocks({
            get: {
                '/api/projects/:team_id/marketing_analytics/setup_plan': () => [
                    200,
                    {
                        suggestions: [
                            {
                                id: 'mark_goal_as_revenue:purchase',
                                kind: 'mark_goal_as_revenue',
                                also_recommended: [],
                                title: 'Mark a revenue goal',
                                evidence: 'Choose which goal measures revenue.',
                                source: 'deterministic',
                                severity: 'info',
                                unlocks: [],
                                apply: {
                                    op: 'update_conversion_goal',
                                    conversion_goal_id: 'purchase',
                                    patch: { counts_as_revenue: true },
                                },
                            },
                        ],
                        readiness: [],
                        degraded: [],
                        truncated: false,
                        summary: '',
                    },
                ],
            },
        })
        initKeaTests()
        localStorage.removeItem('marketing-goal-suggestions-expanded')
        const unmountMarketing = marketingAnalyticsLogic.mount()
        const unmountSetup = setupPlanLogic.mount()
        const view = render(<NewMarketingAnalyticsDashboard />)
        try {
            await screen.findByText('Mark a revenue goal')
            fireEvent.click(screen.getByText('Suggested conversion goals (1)'))
            expect(localStorage.getItem('marketing-goal-suggestions-expanded')).toBe('false')
            view.unmount()
            render(<NewMarketingAnalyticsDashboard />)
            expect(
                screen
                    .getByText('Suggested conversion goals (1)')
                    .closest('[aria-expanded]')
                    ?.getAttribute('aria-expanded')
            ).toBe('false')
            fireEvent.click(screen.getByText('Suggested conversion goals (1)'))
            fireEvent.click(screen.getByText('Review change', { exact: true }))
            await waitFor(() => expect(marketingAnalyticsLogic.values.activeTab).toBe(MarketingAnalyticsTab.SETUP))
            expect(marketingAnalyticsLogic.values.setupSection).toBe(SetupSection.CONVERSION_GOALS)
            expect(setupPlanLogic.values.reviewingSuggestion?.id).toBe('mark_goal_as_revenue:purchase')
            fireEvent.click(screen.getByText('Dismiss'))
            await waitFor(() => expect(screen.queryByText('Suggested conversion goals (1)')).toBeNull())
        } finally {
            cleanup()
            setupPlanLogic.actions.restoreAllDismissed()
            localStorage.removeItem('marketing-goal-suggestions-expanded')
            unmountSetup()
            unmountMarketing()
        }
    })
})
