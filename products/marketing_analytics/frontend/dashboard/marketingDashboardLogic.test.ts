import { expectLogic } from 'kea-test-utils'

import { teamLogic } from 'scenes/teamLogic'
import { marketingAnalyticsLogic } from 'scenes/web-analytics/tabs/marketing-analytics/frontend/logic/marketingAnalyticsLogic'

import {
    ConversionGoalFilter,
    MarketingAnalyticsAttributionBreakdown,
    NodeKind,
    WebStatsBreakdown,
} from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import { PropertyFilterType, PropertyMathType, PropertyOperator, TeamType } from '~/types'

import { RETENTION_MAX_ACQUISITION_DAYS, marketingDashboardLogic } from './marketingDashboardLogic'

const eventGoal = (id: string, extra: Partial<ConversionGoalFilter> = {}): ConversionGoalFilter =>
    ({
        kind: NodeKind.EventsNode,
        event: 'purchase',
        conversion_goal_id: id,
        conversion_goal_name: id,
        schema_map: {},
        ...extra,
    }) as ConversionGoalFilter

const loadGoals = async (goals: ConversionGoalFilter[]): Promise<void> => {
    await expectLogic(() =>
        teamLogic.actions.loadCurrentTeamSuccess({
            ...teamLogic.values.currentTeam!,
            marketing_analytics_config: { conversion_goals: goals },
        } as TeamType)
    ).toFinishAllListeners()
}

describe('marketingDashboardLogic', () => {
    let logic: ReturnType<typeof marketingDashboardLogic.build>

    beforeEach(() => {
        initKeaTests()
        marketingAnalyticsLogic.mount()
        logic = marketingDashboardLogic()
        logic.mount()
    })

    afterEach(() => {
        if (logic.cache.mounted) {
            logic.unmount()
        }
    })

    it('maps the page breakdown onto every web stats table', async () => {
        marketingAnalyticsLogic.actions.setDashboardBreakdown(MarketingAnalyticsAttributionBreakdown.Campaign)
        await expectLogic(logic).toFinishAllListeners()

        for (const query of [
            logic.values.overviewTableQuery,
            logic.values.acquisitionTableQuery,
            logic.values.engagementTableQuery,
        ]) {
            expect(query.breakdownBy).toBe(WebStatsBreakdown.InitialUTMCampaign)
        }
        expect(logic.values.retentionQuery.breakdownBy).toBe(MarketingAnalyticsAttributionBreakdown.Campaign)
    })

    it('asks each table only for the columns its section shows', () => {
        expect(logic.values.overviewTableQuery).toMatchObject({ includeSessionDuration: true })
        expect(logic.values.acquisitionTableQuery).toMatchObject({ includeTrafficMetrics: true })
        // Bounce rate is dropped by the backend when a conversion goal is set, so Engagement has to
        // be its own query rather than a column on the Conversion one.
        expect(logic.values.engagementTableQuery).toMatchObject({
            includeTrafficMetrics: true,
            includeBounceRate: true,
            includeSessionDuration: true,
        })
        expect(logic.values.engagementTableQuery.conversionGoal).toBeUndefined()
    })

    it('threads the page filters into every query', async () => {
        const properties = [
            {
                type: PropertyFilterType.Session,
                key: '$channel_type',
                operator: PropertyOperator.Exact,
                value: 'Direct',
            },
        ]
        marketingAnalyticsLogic.actions.setDashboardProperties(properties as any)
        await loadGoals([eventGoal('signups', { counts_as_customer: true })])

        expect(logic.values.webOverviewQuery.properties).toEqual(properties)
        expect(logic.values.acquisitionTableQuery.properties).toEqual(properties)
        expect(logic.values.retentionQuery.properties).toEqual(properties)
        expect(logic.values.conversionTableQuery?.properties).toEqual(properties)
    })

    it('drops the comparison for an all-time range', async () => {
        marketingAnalyticsLogic.actions.setDates('all', null)
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.compareFilter).toEqual({ compare: false })
        expect(logic.values.retentionQuery.comparePreviousPeriod).toBe(false)
    })

    it('clamps a retention window the backend would refuse', async () => {
        marketingAnalyticsLogic.actions.setDates('-180d', null)
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.retentionAcquisitionRange.clamped).toBe(true)

        marketingAnalyticsLogic.actions.setDates(`-${RETENTION_MAX_ACQUISITION_DAYS - 1}d`, null)
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.retentionAcquisitionRange).toMatchObject({
            clamped: false,
            dateRange: { date_from: `-${RETENTION_MAX_ACQUISITION_DAYS - 1}d` },
        })
    })

    it('builds a revenue query only from goals that total an amount', async () => {
        await loadGoals([eventGoal('signups', { counts_as_customer: true })])
        expect(logic.values.revenueQuery).toBeNull()

        // counts_as_revenue without sum math cannot be totalled, so it must not reach the query.
        await loadGoals([eventGoal('purchases', { counts_as_revenue: true })])
        expect(logic.values.revenueQuery).toBeNull()

        await loadGoals([
            eventGoal('purchases', {
                counts_as_revenue: true,
                math: PropertyMathType.Sum,
                math_property: 'revenue',
            }),
        ])
        expect(logic.values.revenueQuery?.series).toMatchObject([
            { kind: NodeKind.EventsNode, event: 'purchase', math: PropertyMathType.Sum, math_property: 'revenue' },
        ])
    })

    it('falls back to a customer goal, then to the first goal', async () => {
        await loadGoals([eventGoal('first'), eventGoal('customer', { counts_as_customer: true })])
        expect(logic.values.selectedConversionGoal?.conversion_goal_id).toBe('customer')

        await loadGoals([eventGoal('only')])
        expect(logic.values.selectedConversionGoal?.conversion_goal_id).toBe('only')

        await loadGoals([])
        expect(logic.values.selectedConversionGoal).toBeNull()
        expect(logic.values.conversionTableQuery).toBeNull()
    })
})
