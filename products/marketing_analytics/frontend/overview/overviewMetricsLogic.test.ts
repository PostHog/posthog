import { MOCK_TEAM_ID } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import { marketingAnalyticsLogic } from 'scenes/web-analytics/tabs/marketing-analytics/frontend/logic/marketingAnalyticsLogic'

import type { OverviewMetricCardItem } from '~/queries/nodes/OverviewGrid/OverviewMetricCardGrid'
import { initKeaTests } from '~/test/init'

import { moveOverviewMetric, shownOverviewMetrics, toggleOverviewMetric } from './overviewMetricConfiguration'
import { overviewMetricsLogic } from './overviewMetricsLogic'

const platformItems: OverviewMetricCardItem[] = ['Cost', 'Clicks', 'Impressions', 'CPC', 'CTR', 'Reported ROAS'].map(
    (key) => ({ key, value: 1, kind: 'unit' })
)
const posthogItems: OverviewMetricCardItem[] = ['Trial started', 'Cost Per Trial started', 'Demo booked'].map(
    (key) => ({ key, value: 1, kind: 'unit' })
)
const items = [...platformItems, ...posthogItems]

describe('overview metric configuration', () => {
    beforeEach(() => {
        localStorage.clear()
        initKeaTests()
    })

    it('discards canceled edits and persists the applied selection for the view only', () => {
        const logic = overviewMetricsLogic({ viewKey: 'ad-performance' })
        const unmount = logic.mount()
        logic.actions.openEditor()
        logic.actions.setDraftSelection(['Cost'])
        logic.actions.closeEditor()
        expect(logic.values.selection).toBeNull()
        logic.actions.openEditor()
        expect(logic.values.draftSelection).toBeNull()
        logic.actions.setDraftSelection(['Clicks', 'Cost', 'Trial started'])
        logic.actions.applySelection(logic.values.draftSelection!)
        expect(logic.values.editorOpen).toBe(false)
        unmount()
        const restored = overviewMetricsLogic({ viewKey: 'ad-performance' })
        const unmountRestored = restored.mount()
        expect(restored.values.selection).toEqual(['Clicks', 'Cost', 'Trial started'])
        expect(restored.values.draftSelection).toBeNull()
        expect(
            JSON.parse(
                localStorage.getItem(
                    `${MOCK_TEAM_ID}__.products.marketingAnalytics.overviewMetricsLogic.ad-performance.selection`
                )!
            )
        ).toEqual(['Clicks', 'Cost', 'Trial started'])
        const anotherView = overviewMetricsLogic({ viewKey: 'another-view' })
        const unmountOther = anotherView.mount()
        expect(anotherView.values.selection).toBeNull()
        unmountOther()
        unmountRestored()
    })

    it('toggles and moves metrics, ignoring additions past five', () => {
        const five = ['Cost', 'Clicks', 'Impressions', 'CPC', 'CTR']
        expect(toggleOverviewMetric(five, 'Trial started')).toEqual(five)
        expect(toggleOverviewMetric(toggleOverviewMetric(five, 'CTR'), 'Trial started')).toEqual([
            'Cost',
            'Clicks',
            'Impressions',
            'CPC',
            'Trial started',
        ])
        expect(moveOverviewMetric(five, 'Clicks', -1).slice(0, 2)).toEqual(['Clicks', 'Cost'])
        expect(moveOverviewMetric(five, 'Cost', -1)).toEqual(five)
    })

    it.each([
        ['none', ['Cost', 'Trial started']],
        ['posthog', ['Cost', 'Clicks']],
        ['platforms', ['Trial started']],
    ])('reports %s hidden when applying that selection, and nothing on cancel', async (value, selection) => {
        const logic = overviewMetricsLogic({ viewKey: 'ad-performance' })
        const unmount = logic.mount()
        logic.actions.openEditor()
        logic.actions.setDraftSelection(selection)
        await expectLogic(logic, () => logic.actions.closeEditor()).toNotHaveDispatchedActions([
            'reportDashboardControlUsed',
        ])
        await expectLogic(logic, () => logic.actions.applySelection(selection)).toDispatchActions([
            marketingAnalyticsLogic.actionCreators.reportDashboardControlUsed(
                'overview',
                'metric_configuration_applied',
                value
            ),
        ])
        unmount()
    })

    it.each([
        [
            'defaults to three platform and two PostHog metrics',
            items,
            null,
            ['Cost', 'Clicks', 'Impressions', 'Trial started', 'Cost Per Trial started'],
        ],
        [
            'defaults to five platform metrics without goals',
            platformItems,
            null,
            ['Cost', 'Clicks', 'Impressions', 'CPC', 'CTR'],
        ],
        [
            'keeps the saved order and drops removed goals',
            items,
            ['Removed goal', 'Demo booked', 'Cost'],
            ['Demo booked', 'Cost'],
        ],
        [
            'falls back to the default when no saved metric remains',
            platformItems,
            ['Removed goal'],
            ['Cost', 'Clicks', 'Impressions', 'CPC', 'CTR'],
        ],
    ])('%s', (_, available, selection, expected) => {
        expect(shownOverviewMetrics(available, selection).map((item) => item.key)).toEqual(expected)
    })
})
