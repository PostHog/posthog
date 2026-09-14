import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import { teamLogic } from 'scenes/teamLogic'

import { ConversionGoalFilter, NodeKind, WebAnalyticsOrderByFields } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import { PropertyFilterType, PropertyOperator } from '~/types'

import { marketingAcquisitionLogic } from './marketingAcquisitionLogic'

describe('marketingAcquisitionLogic', () => {
    it('keeps customer goal filters and falls back when a selected goal is removed or unmarked', async () => {
        initKeaTests()
        const logic = marketingAcquisitionLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        const goal: ConversionGoalFilter = {
            kind: NodeKind.EventsNode,
            event: 'customer_created',
            conversion_goal_id: 'customer',
            conversion_goal_name: 'New customer',
            schema_map: {},
            counts_as_customer: true,
            properties: [
                { type: PropertyFilterType.Event, key: 'plan', value: 'paid', operator: PropertyOperator.Exact },
            ],
        }
        const loadGoals = async (goals: ConversionGoalFilter[]): Promise<void> => {
            await expectLogic(logic, () =>
                teamLogic.actions.loadCurrentTeamSuccess({
                    ...MOCK_DEFAULT_TEAM,
                    marketing_analytics_config: { conversion_goals: goals },
                })
            ).toFinishAllListeners()
        }
        await loadGoals([goal, { ...goal, kind: NodeKind.ActionsNode, id: 42, conversion_goal_id: 'action' }])
        expect(logic.values.customerConversionGoal).toEqual({
            customEventName: 'customer_created',
            properties: goal.properties,
        })
        logic.actions.setCustomerGoalId('action')
        expect(logic.values.customerConversionGoal).toEqual({ actionId: 42, properties: goal.properties })
        await loadGoals([goal])
        expect(logic.values.selectedCustomerGoal?.conversion_goal_id).toBe('customer')
        await loadGoals([{ ...goal, counts_as_customer: false }])
        expect(logic.values.customerConversionGoal).toBeNull()
        logic.unmount()
    })

    it('toggles metric sorting independently for acquisition and engagement', () => {
        initKeaTests()
        const logic = marketingAcquisitionLogic()
        logic.mount()
        try {
            logic.actions.toggleTrafficSort('acquisition', WebAnalyticsOrderByFields.Views)
            expect(logic.values.trafficOrderBy.acquisition).toEqual([WebAnalyticsOrderByFields.Views, 'DESC'])
            logic.actions.toggleTrafficSort('acquisition', WebAnalyticsOrderByFields.Views)
            expect(logic.values.trafficOrderBy.acquisition).toEqual([WebAnalyticsOrderByFields.Views, 'ASC'])
            logic.actions.toggleTrafficSort('engagement', WebAnalyticsOrderByFields.BounceRate)
            expect(logic.values.trafficOrderBy.engagement).toEqual([WebAnalyticsOrderByFields.BounceRate, 'DESC'])
            expect(logic.values.trafficOrderBy.acquisition).toEqual([WebAnalyticsOrderByFields.Views, 'ASC'])
            logic.actions.toggleTrafficSort('acquisition', WebAnalyticsOrderByFields.UniqueConversions)
            expect(logic.values.trafficOrderBy.acquisition).toEqual([
                WebAnalyticsOrderByFields.UniqueConversions,
                'DESC',
            ])
        } finally {
            logic.unmount()
        }
    })
})
