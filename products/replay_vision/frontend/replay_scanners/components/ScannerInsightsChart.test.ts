import { getDisplayNameFromEntityFilter } from 'scenes/insights/utils'

import { EntityFilter } from '~/types'

import { buildQuery } from './ScannerInsightsChart'

describe('ScannerInsightsChart', () => {
    describe('buildQuery scorer series', () => {
        // The three percentile series share the `$recording_observed` event and differ only by `math`,
        // which the label resolver never reads. Without a per-series name they all humanize to
        // "recording_observed" in the legend and tooltip, so this guards the names that keep them apart.
        it('gives each percentile series a distinct display label', () => {
            const query = buildQuery('scanner-1', 'scorer', '-7d', null)

            const labels = query.series.map((s) => getDisplayNameFromEntityFilter(s as EntityFilter))

            expect(labels).toEqual(['Median', 'P90', 'Average'])
            expect(new Set(labels).size).toBe(labels.length)
        })
    })
})
