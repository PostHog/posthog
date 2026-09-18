import { NodeKind } from '~/queries/schema/schema-general'
import { BaseMathType } from '~/types'

import { trafficChartSeries } from './trafficChartSeries'

describe('trafficChartSeries', () => {
    const eventGoal = { customEventName: 'purchase' }
    const actionGoal = { actionId: 7 }

    it.each([
        ['visitors', null, { kind: NodeKind.EventsNode, event: null, math: BaseMathType.UniqueUsers }],
        ['sessions', eventGoal, { kind: NodeKind.EventsNode, event: null, math: BaseMathType.UniqueSessions }],
        ['pageviews', eventGoal, { kind: NodeKind.EventsNode, event: null, math: BaseMathType.TotalCount }],
        ['new_customers', eventGoal, { kind: NodeKind.EventsNode, event: 'purchase', math: BaseMathType.UniqueUsers }],
        ['new_customers', actionGoal, { kind: NodeKind.ActionsNode, id: 7, math: BaseMathType.UniqueUsers }],
        ['new_customers', null, { kind: NodeKind.EventsNode, event: null, math: BaseMathType.UniqueUsers }],
    ] as const)('%s with goal %j', (metric, goal, expected) => {
        expect(trafficChartSeries(metric, goal)).toMatchObject(expected)
    })
})
