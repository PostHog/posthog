import { MOCK_TEAM_ID } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import { marketingAnalyticsLogic } from 'scenes/web-analytics/tabs/marketing-analytics/frontend/logic/marketingAnalyticsLogic'

import type { OverviewMetricCardItem } from '~/queries/nodes/OverviewGrid/OverviewMetricCardGrid'
import { initKeaTests } from '~/test/init'

import { defaultOverviewMetricConfiguration, overviewMetricsForGroup } from './overviewMetricConfiguration'
import { overviewMetricsLogic } from './overviewMetricsLogic'

const items: OverviewMetricCardItem[] = [
    { key: 'Cost', value: 100, kind: 'currency' },
    { key: 'Clicks', value: 200, kind: 'unit' },
    { key: 'Trial started', value: 20, kind: 'unit' },
    { key: 'Cost Per Trial started', value: 5, kind: 'currency' },
]

describe('overview metric configuration', () => {
    beforeEach(() => {
        localStorage.clear()
        initKeaTests()
    })

    it('discards canceled edits and persists applied visibility, order, and collapsed groups for the view', () => {
        const logic = overviewMetricsLogic({ viewKey: 'ad-performance' })
        const unmount = logic.mount()
        logic.actions.configureMetrics(logic.values.configuration)
        logic.actions.updateDraftGroup('platforms', { hidden: ['Cost'], order: ['Clicks', 'Cost'] })
        expect(logic.values.configuration.platforms.hidden).toEqual([])
        logic.actions.closeConfiguration()
        expect(logic.values.configuration.platforms.hidden).toEqual([])
        logic.actions.configureMetrics(logic.values.configuration)
        logic.actions.updateDraftGroup('platforms', { hidden: ['Cost'], order: ['Clicks', 'Cost'] })
        logic.actions.applyConfiguration(logic.values.draftConfiguration!)
        logic.actions.setGroupCollapsed('posthog', true)
        const saved = logic.values.configuration
        unmount()
        const restored = overviewMetricsLogic({ viewKey: 'ad-performance' })
        const unmountRestored = restored.mount()
        expect(restored.values.configuration).toEqual(saved)
        expect(restored.values.draftConfiguration).toBeNull()
        expect(
            JSON.parse(
                localStorage.getItem(
                    `${MOCK_TEAM_ID}__.products.marketingAnalytics.overviewMetricsLogic.ad-performance.configuration`
                )!
            )
        ).toEqual(saved)
        const anotherView = overviewMetricsLogic({ viewKey: 'another-view' })
        const unmountOther = anotherView.mount()
        expect(anotherView.values.configuration).toEqual(defaultOverviewMetricConfiguration())
        unmountOther()
        unmountRestored()
    })

    it.each([
        ['none', [], []],
        ['platforms', ['Cost'], []],
        ['posthog', [], ['Trial started']],
        ['both', ['Cost'], ['Trial started']],
    ])(
        'reports %s when applying with those groups hidden, and nothing on cancel',
        async (value, platforms, posthogHidden) => {
            const logic = overviewMetricsLogic({ viewKey: 'ad-performance' })
            const unmount = logic.mount()
            logic.actions.configureMetrics(logic.values.configuration)
            logic.actions.updateDraftGroup('platforms', { hidden: platforms })
            logic.actions.updateDraftGroup('posthog', { hidden: posthogHidden })
            await expectLogic(logic, () => logic.actions.closeConfiguration()).toNotHaveDispatchedActions([
                'reportDashboardControlUsed',
            ])
            logic.actions.configureMetrics(logic.values.configuration)
            logic.actions.updateDraftGroup('platforms', { hidden: platforms })
            logic.actions.updateDraftGroup('posthog', { hidden: posthogHidden })
            await expectLogic(logic, () =>
                logic.actions.applyConfiguration(logic.values.draftConfiguration!)
            ).toDispatchActions([
                marketingAnalyticsLogic.actionCreators.reportDashboardControlUsed(
                    'overview',
                    'metric_configuration_applied',
                    value
                ),
            ])
            unmount()
        }
    )

    it('keeps platform metrics separate, appends new goals, and drops removed metrics from saved ordering', () => {
        const configuration = defaultOverviewMetricConfiguration()
        configuration.platforms.order = ['Clicks', 'Cost']
        configuration.posthog.order = ['Removed goal', 'Cost Per Trial started', 'Trial started']
        expect(overviewMetricsForGroup(items, 'platforms', configuration).map((item) => item.key)).toEqual([
            'Clicks',
            'Cost',
        ])
        expect(
            overviewMetricsForGroup(
                [...items, { key: 'New goal', value: 10, kind: 'unit' }],
                'posthog',
                configuration
            ).map((item) => item.key)
        ).toEqual(['Cost Per Trial started', 'Trial started', 'New goal'])
    })

    it('resets a saved hidden section without changing it until Apply', () => {
        const logic = overviewMetricsLogic({ viewKey: 'ad-performance' })
        const unmount = logic.mount()
        const configuration = defaultOverviewMetricConfiguration()
        configuration.platforms = { hidden: ['Cost', 'Clicks'], order: ['Clicks', 'Cost'], collapsed: true }
        logic.actions.applyConfiguration(configuration)
        logic.actions.configureMetrics(logic.values.configuration)
        logic.actions.resetDraft()
        expect(logic.values.configuration.platforms.collapsed).toBe(true)
        expect(logic.values.draftConfiguration).toEqual(defaultOverviewMetricConfiguration())
        logic.actions.applyConfiguration(logic.values.draftConfiguration!)
        expect(logic.values.configuration).toEqual(defaultOverviewMetricConfiguration())
        unmount()
    })
})
