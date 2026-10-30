import type { SeriesNode } from 'scenes/insights/filters/ActionFilter/seriesNode'

import { FunnelsDataWarehouseNode, FunnelsQuery, NodeKind } from '~/queries/schema/schema-general'
import { FilterLogicalOperator, StepOrderValue } from '~/types'

import { getFunnelStepEntity, getFunnelStepSeries, isRepeatedFunnelStep } from './funnelStepSeries'

describe('funnelStepSeries', () => {
    const pageviews = { kind: NodeKind.EventsNode as const, event: '$pageview', name: '$pageview' }
    const signups = { kind: NodeKind.ActionsNode as const, id: 7, name: 'Signed up' }
    const warehouseTable = (table_name: string): FunnelsDataWarehouseNode => ({
        kind: NodeKind.FunnelsDataWarehouseNode,
        id: table_name,
        table_name,
        id_field: 'id',
        timestamp_field: 'created_at',
        aggregation_target_field: 'customer_id',
    })

    it.each<{ case: string; query: FunnelsQuery; stepIndex: number; stepName: string; expected: SeriesNode | null }>([
        {
            case: 'a step to the series at its index',
            query: { kind: NodeKind.FunnelsQuery, series: [pageviews, signups] },
            stepIndex: 1,
            stepName: 'Signed up',
            expected: signups,
        },
        {
            case: 'a step of an unordered funnel to no series, because it counts completed series',
            query: {
                kind: NodeKind.FunnelsQuery,
                series: [pageviews, signups],
                funnelsFilter: { funnelOrderType: StepOrderValue.UNORDERED },
            },
            stepIndex: 1,
            stepName: 'Completed 2 steps',
            expected: null,
        },
        {
            case: 'a step the edited query no longer holds to no series',
            query: { kind: NodeKind.FunnelsQuery, series: [pageviews] },
            stepIndex: 1,
            stepName: 'Signed up',
            expected: null,
        },
        {
            case: 'an events series saved without a name to its event',
            query: { kind: NodeKind.FunnelsQuery, series: [{ kind: NodeKind.EventsNode, event: '$autocapture' }] },
            stepIndex: 0,
            stepName: '$autocapture',
            expected: { kind: NodeKind.EventsNode, event: '$autocapture', name: '$autocapture' },
        },
        {
            case: 'a renamed action to the name the runner gave the step, keeping its custom name',
            query: {
                kind: NodeKind.FunnelsQuery,
                series: [{ ...signups, custom_name: 'Converted' }],
            },
            stepIndex: 0,
            stepName: 'Sign-ups',
            expected: { ...signups, name: 'Sign-ups', custom_name: 'Converted' },
        },
        {
            case: 'an action series saved without a name to the name the runner gave the step',
            query: { kind: NodeKind.FunnelsQuery, series: [{ kind: NodeKind.ActionsNode, id: 7 }] },
            stepIndex: 0,
            stepName: 'Signed up',
            expected: { kind: NodeKind.ActionsNode, id: 7, name: 'Signed up' },
        },
    ])('resolves $case', ({ query, stepIndex, stepName, expected }) => {
        expect(getFunnelStepSeries(query, stepIndex, { name: stepName })).toEqual(expected)
    })

    it('labels an unordered funnel step by the step name', () => {
        const query: FunnelsQuery = {
            kind: NodeKind.FunnelsQuery,
            series: [pageviews, signups],
            funnelsFilter: { funnelOrderType: StepOrderValue.UNORDERED },
        }

        expect(getFunnelStepEntity(query, 0, { name: 'Completed 1 step', custom_name: null })).toEqual({
            id: null,
            name: 'Completed 1 step',
            custom_name: null,
        })
    })

    it.each<[string, SeriesNode, SeriesNode, boolean]>([
        ['the same event', pageviews, { ...pageviews, name: 'Viewed a page' }, true],
        ['different events', pageviews, { kind: NodeKind.EventsNode, event: '$screen' }, false],
        ['tables with different names', warehouseTable('invoices'), warehouseTable('charges'), false],
        ['the same table', warehouseTable('invoices'), warehouseTable('invoices'), true],
        [
            'groups with the same members',
            { kind: NodeKind.GroupNode, operator: FilterLogicalOperator.Or, nodes: [pageviews, signups] },
            { kind: NodeKind.GroupNode, operator: FilterLogicalOperator.Or, nodes: [pageviews, signups] },
            true,
        ],
        [
            'groups with different members',
            { kind: NodeKind.GroupNode, operator: FilterLogicalOperator.Or, nodes: [pageviews, signups] },
            { kind: NodeKind.GroupNode, operator: FilterLogicalOperator.Or, nodes: [pageviews] },
            false,
        ],
    ])('tells whether two steps on %s repeat', (_case, previousSeries, series, expected) => {
        expect(isRepeatedFunnelStep(series, previousSeries)).toBe(expected)
    })
})
