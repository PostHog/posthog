import { dayjs } from 'lib/dayjs'

import { NodeKind } from '~/queries/schema/schema-general'

import { rangeReachesBefore } from './rangeReachesBefore'

const CUTOFF = dayjs.utc('2024-12-01')

const insightViz = (series: any[] = [{ kind: NodeKind.EventsNode }]): any => ({
    kind: NodeKind.InsightVizNode,
    source: { kind: NodeKind.TrendsQuery, series },
})

describe('rangeReachesBefore', () => {
    it.each([
        ['a range starting before the cutoff', insightViz(), '2024-11-30', CUTOFF, true],
        ['a range starting on the cutoff', insightViz(), '2024-12-01', CUTOFF, false],
        ['an insight without a resolved range, like SQL', insightViz(), null, CUTOFF, false],
        [
            'a range over warehouse tables only',
            insightViz([{ kind: NodeKind.DataWarehouseNode }]),
            '2024-01-01',
            CUTOFF,
            false,
        ],
        ['a project with no deletion scheduled', insightViz(), '2024-01-01', null, false],
    ])('%s', (_name, query, resolvedDateFrom, cutoff, expected) => {
        expect(rangeReachesBefore({ query, resolvedDateFrom, cutoff })).toBe(expected)
    })
})
