import { NodeKind } from '~/queries/schema/schema-general'

import { showsRetentionDeletion } from './showsRetentionDeletion'

const EVENTS_QUERY: any = { kind: NodeKind.TrendsQuery, series: [{ kind: NodeKind.EventsNode }] }
const WAREHOUSE_QUERY: any = { kind: NodeKind.TrendsQuery, series: [{ kind: NodeKind.DataWarehouseNode }] }

describe('showsRetentionDeletion', () => {
    it.each([
        ['an events trend over dates', false, EVENTS_QUERY, null, true],
        ['a comparison against the previous period', false, EVENTS_QUERY, { compare: true }, false],
        ['a trend over warehouse tables only', false, WAREHOUSE_QUERY, null, false],
        ['stickiness, whose x-axis is not dates', true, EVENTS_QUERY, null, false],
    ])('%s', (_name, isStickiness, querySource, compareFilter, expected) => {
        expect(showsRetentionDeletion({ isStickiness, querySource, compareFilter })).toEqual(expected)
    })
})
