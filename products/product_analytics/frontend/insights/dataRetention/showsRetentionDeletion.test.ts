import { NodeKind } from '~/queries/schema/schema-general'
import { ChartDisplayType } from '~/types'

import { shadesRetentionDeletion, showsRetentionDeletion } from './showsRetentionDeletion'

const EVENTS_QUERY: any = { kind: NodeKind.TrendsQuery, series: [{ kind: NodeKind.EventsNode }] }
const WAREHOUSE_QUERY: any = { kind: NodeKind.TrendsQuery, series: [{ kind: NodeKind.DataWarehouseNode }] }

const insightViz = (source: Record<string, any>): any => ({ kind: NodeKind.InsightVizNode, source })

describe('showsRetentionDeletion', () => {
    it.each([
        ['an events trend over dates', false, EVENTS_QUERY, null, true],
        ['a comparison against the previous period', false, EVENTS_QUERY, { compare: true }, false],
        ['a trend over warehouse tables only', false, WAREHOUSE_QUERY, null, false],
        ['stickiness, whose x-axis is not dates', true, EVENTS_QUERY, null, false],
    ])('%s', (_name, isStickiness, querySource, compareFilter, expected) => {
        expect(showsRetentionDeletion({ isStickiness, querySource, compareFilter })).toEqual(expected)
    })

    describe('shadesRetentionDeletion', () => {
        it.each([
            ['a line trend', insightViz(EVENTS_QUERY), true],
            [
                'a bar trend',
                insightViz({ ...EVENTS_QUERY, trendsFilter: { display: ChartDisplayType.ActionsBar } }),
                true,
            ],
            [
                'a single-number trend',
                insightViz({ ...EVENTS_QUERY, trendsFilter: { display: ChartDisplayType.BoldNumber } }),
                false,
            ],
            [
                'a line trend compared to the previous period',
                insightViz({ ...EVENTS_QUERY, compareFilter: { compare: true } }),
                false,
            ],
            ['a funnel', insightViz({ kind: NodeKind.FunnelsQuery, series: [{ kind: NodeKind.EventsNode }] }), false],
        ])('%s', (_name, query, expected) => {
            expect(shadesRetentionDeletion(query)).toBe(expected)
        })
    })
})
