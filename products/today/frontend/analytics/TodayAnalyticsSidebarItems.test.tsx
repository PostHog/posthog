import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { router } from 'kea-router'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { sidePanelStateLogic } from '~/layout/navigation-3000/sidepanel/sidePanelStateLogic'
import { SidebarSearchList } from '~/layout/today/sidebar/SidebarSearchList'
import { useMocks } from '~/mocks/jest'
import { CurrencyCode } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import { SidePanelTab } from '~/types'

import { SidebarAgentListener } from 'products/ui_customization/frontend/SidebarAgentListener'
import { SidebarButton } from 'products/ui_customization/frontend/SidebarButton'
import { sidebarCustomizationLogic } from 'products/ui_customization/frontend/sidebarCustomizationLogic'

import { analyticsSidebarProps } from './analyticsSidebarConfiguration'
import { TodayAnalyticsMetric } from './TodayAnalyticsMetric'
import { TodayAnalyticsSidebar } from './TodayAnalyticsSidebar'
import { resolveSidebarTarget } from './todayAnalyticsSidebarTargets'

jest.mock('products/ui_customization/frontend/SidebarAgentListener', () => ({
    SidebarAgentListener: jest.fn(() => null),
}))

describe('Analytics sidebar options', () => {
    beforeEach(() => {
        // The layout persists per person, so one test's saved layout would leak into the next.
        localStorage.clear()
        initKeaTests()
        featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.UI_CUSTOMIZATION]: true })
    })
    afterEach(cleanup)

    it('hides customization and the AI listener when disabled, even with a cached custom layout', () => {
        featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.PHAI_SANDBOX_MODE]: true })
        sidebarCustomizationLogic(analyticsSidebarProps()).mount()
        sidebarCustomizationLogic(analyticsSidebarProps()).actions.requestSidebarSuccess({
            customized: true,
            layout: {
                version: 1,
                sections: [
                    {
                        id: 'custom',
                        items: [{ type: 'link', to: { kind: 'page', page: 'alerts' }, label: 'Custom alerts' }],
                    },
                ],
            },
        })
        const { container } = render(<TodayAnalyticsSidebar />)

        expect(screen.queryByText('Custom alerts')).toBeNull()
        expect(container.querySelector('[data-attr="analytics-sidebar-browse"]')).not.toBeNull()
        expect(container.querySelector('[data-attr="analytics-sidebar-customize"]')).toBeNull()
        expect(container.querySelector('[data-attr="analytics-sidebar-reset"]')).toBeNull()
        expect(container.querySelector('[data-attr="analytics-sidebar-retry"]')).toBeNull()
        expect(SidebarAgentListener).not.toHaveBeenCalled()
    })

    it('offers only personalization before a layout is saved, and opens PostHog AI in the side panel', () => {
        featureFlagLogic.actions.setFeatureFlags([], {
            [FEATURE_FLAGS.UI_CUSTOMIZATION]: true,
            [FEATURE_FLAGS.PHAI_SANDBOX_MODE]: true,
        })
        sidePanelStateLogic.mount()
        router.actions.push(urls.analyticsList())
        const { container } = render(<TodayAnalyticsSidebar />)
        expect(container.querySelector('[data-attr="analytics-sidebar-reset"]')).toBeNull()

        fireEvent.click(container.querySelector('[data-attr="analytics-sidebar-customize"]')!)

        expect(sidePanelStateLogic.values.selectedTab).toBe(SidePanelTab.Max)
        expect(sidePanelStateLogic.values.selectedTabOptions).toMatch(/^!Help me personalize my Analytics sidebar/)
        expect(router.values.location.pathname).toContain(urls.analyticsList())
    })

    it('keeps a pending metric insight available as a link and keyboard option', () => {
        useMocks({ get: { '/api/projects/:team_id/insights/': async () => await new Promise<never>(() => {}) } })

        const { container } = render(
            <SidebarSearchList query="" onQueryChange={jest.fn()} searchLabel="Search analytics" dataAttr="search">
                <TodayAnalyticsMetric
                    item={{ type: 'metric', insight: 'aB3dE5fG', label: 'Signups this week' }}
                    value="growth:0"
                    active={false}
                />
            </SidebarSearchList>
        )

        const link = container.querySelector('[data-attr="analytics-sidebar-metric"]')
        expect(link?.getAttribute('role')).toBe('option')
        expect(link?.textContent).toContain('Signups this week')
        expect(link?.getAttribute('href')).toContain('aB3dE5fG')
    })

    it('formats a loaded metric with the project currency and hides a disabled change', async () => {
        teamLogic.mount()
        teamLogic.actions.loadCurrentTeamSuccess({ ...MOCK_DEFAULT_TEAM, base_currency: CurrencyCode.EUR })
        useMocks({
            get: {
                '/api/projects/:team_id/insights/': {
                    results: [
                        {
                            query: {
                                kind: 'InsightVizNode',
                                source: {
                                    kind: 'TrendsQuery',
                                    trendsFilter: { aggregationAxisFormat: 'currency', metricShowChange: false },
                                },
                            },
                            result: [{ count: 125, data: [10, 20, 30], labels: ['Mon', 'Tue', 'Wed'] }],
                        },
                    ],
                },
            },
        })

        const { container } = render(
            <SidebarSearchList query="" onQueryChange={jest.fn()} searchLabel="Search analytics" dataAttr="search">
                <TodayAnalyticsMetric
                    item={{ type: 'metric', insight: 'aB3dE5fG', label: 'Revenue' }}
                    value="growth:0"
                    active={false}
                />
            </SidebarSearchList>
        )

        expect(await screen.findByText(/€125/)).toBeTruthy()
        expect(container.querySelector('[data-attr="metric-change-pill"]')).toBeNull()
    })

    it.each(['primary', 'outline'] as const)('includes a %s custom button in arrow navigation', (variant) => {
        const { container } = render(
            <SidebarSearchList query="" onQueryChange={jest.fn()} searchLabel="Search analytics" dataAttr="search">
                <SidebarButton
                    value="growth:0"
                    dataAttr="analytics-sidebar-growth-button"
                    resolved={resolveSidebarTarget({ kind: 'page', page: 'new_insight' }, 'New insight')}
                    target={{
                        type: 'button',
                        to: { kind: 'page', page: 'new_insight' },
                        label: 'New insight',
                        variant,
                    }}
                />
            </SidebarSearchList>
        )

        const input = container.querySelector('[data-attr="search"]') as HTMLInputElement
        const button = container.querySelector('[data-attr="analytics-sidebar-growth-button"]')
        expect(input.getAttribute('role')).toBe('combobox')
        expect(button?.getAttribute('role')).toBe('option')
        expect(button?.textContent).toContain('New insight')
        fireEvent.keyDown(input, { key: 'ArrowDown' })
        expect(button?.hasAttribute('data-highlighted')).toBe(true)
        expect(button?.getAttribute('href')).toContain('insights/new')
        fireEvent.keyDown(input, { key: 'Enter' })
        expect(router.values.location.pathname).toContain('insights/new')
    })
})
