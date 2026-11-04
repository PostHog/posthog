import { HeatmapEventFilter } from 'lib/components/heatmaps/types'
import { SeriesNode } from 'scenes/insights/filters/ActionFilter/seriesNode'

import { NodeKind } from '~/queries/schema/schema-general'

import { heatmapEventFiltersToSeries, seriesToHeatmapEventFilters } from './heatmapEventSeries'

const pricingPage = { key: '$current_url', value: 'pricing', operator: 'icontains', type: 'event' }
const flagOn = { key: '$feature/new-checkout', value: ['true'], operator: 'exact', type: 'event' }

describe('heatmapEventSeries', () => {
    test.each<[string, HeatmapEventFilter[], HeatmapEventFilter[]]>([
        [
            'entries come back in order with their names and properties',
            [
                { id: 'purchased', name: 'purchased', type: 'events', order: 4, properties: [flagOn] },
                { id: '$pageview', name: '$pageview', type: 'events', order: 1, properties: [pricingPage] },
            ],
            [
                { name: '$pageview', properties: [pricingPage], id: '$pageview', type: 'events', order: 0 },
                { name: 'purchased', properties: [flagOn], id: 'purchased', type: 'events', order: 1 },
            ],
        ],
        [
            'an entry with no order or type reads as an event',
            [{ id: 'signed_up' }],
            [{ id: 'signed_up', type: 'events', order: 0 }],
        ],
    ])('%s', (_, stored, expected) => {
        expect(JSON.stringify(seriesToHeatmapEventFilters(heatmapEventFiltersToSeries(stored)))).toEqual(
            JSON.stringify(expected)
        )
    })

    test('a row the picker built drops its node version', () => {
        const series = [
            { kind: NodeKind.EventsNode, event: '$autocapture', name: 'Autocapture', version: 1 } as SeriesNode,
        ]
        expect(JSON.stringify(seriesToHeatmapEventFilters(series))).toEqual(
            JSON.stringify([{ name: 'Autocapture', id: '$autocapture', type: 'events', order: 0 }])
        )
    })
})
