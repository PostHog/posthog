import { defaultConversionGoalFilter } from 'scenes/web-analytics/tabs/marketing-analytics/frontend/components/settings/constants'

import { ConversionGoalFilter, NodeKind } from '~/queries/schema/schema-general'
import { BaseMathType, PropertyMathType, PropertyOperator } from '~/types'

import { findEquivalentConversionGoal } from './findEquivalentConversionGoal'

const goal: ConversionGoalFilter = {
    ...defaultConversionGoalFilter,
    conversion_goal_id: 'saved-goal',
    conversion_goal_name: 'Payments',
    kind: NodeKind.EventsNode,
    event: 'payment_completed',
    math: PropertyMathType.Sum,
    math_property: 'amount',
    counts_as_revenue: true,
}

describe('equivalent conversion goals', () => {
    it.each([
        [
            'different display name',
            { conversion_goal_name: 'Revenue', name: 'Renamed event', custom_name: 'Custom label' },
            true,
        ],
        [
            'explicit defaults',
            { properties: [], fixedProperties: [], counts_as_customer: false, math_multiplier: 1 },
            true,
        ],
        ['different event', { event: 'refund_completed' }, false],
        ['action instead of event', { kind: NodeKind.ActionsNode, id: 12 }, false],
        ['different calculation', { math: PropertyMathType.Average }, false],
        ['different amount', { math_property: 'net_amount' }, false],
        ['different currency mapping', { math_property_revenue_currency: { property: 'currency' } }, false],
        ['different multiplier', { math_multiplier: 0.01 }, false],
        ['different revenue flag', { counts_as_revenue: false }, false],
        ['different customer flag', { counts_as_customer: true }, false],
        [
            'different filters',
            { properties: [{ key: 'status', value: 'paid', operator: PropertyOperator.Exact, type: 'event' }] },
            false,
        ],
        [
            'different fixed filters',
            { fixedProperties: [{ key: 'status', value: 'paid', operator: PropertyOperator.Exact, type: 'event' }] },
            false,
        ],
        ['different attribution mapping', { schema_map: { ...goal.schema_map, utm_source_name: 'source' } }, false],
    ] as const)('compares %s', (_, changes, matches) => {
        const candidate = { ...goal, ...changes, conversion_goal_id: '' } as ConversionGoalFilter
        expect(findEquivalentConversionGoal([goal], candidate)).toEqual(matches ? goal : undefined)
    })

    it('matches an action by ID, with omitted count math and flags treated as defaults', () => {
        const action: ConversionGoalFilter = {
            ...defaultConversionGoalFilter,
            conversion_goal_id: 'action-goal',
            kind: NodeKind.ActionsNode,
            id: 12,
            math: undefined,
        }
        expect(
            findEquivalentConversionGoal([action], {
                ...action,
                math: BaseMathType.TotalCount,
                counts_as_revenue: false,
            })
        ).toBe(action)
        expect(findEquivalentConversionGoal([action], { ...action, id: 13 })).toBeUndefined()
    })
})
