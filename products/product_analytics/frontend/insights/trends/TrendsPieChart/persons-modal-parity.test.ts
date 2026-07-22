import type { IndexedTrendResult } from 'scenes/trends/types'
import { datasetToActorsQuery } from 'scenes/trends/viz/datasetToActorsQuery'

import type { InsightActorsQuery } from '~/queries/schema/schema-general'
import { NodeKind } from '~/queries/schema/schema-general'
import type { ActionFilter, GraphDataset } from '~/types'

/** Verifies that the hog-charts TrendsPieChart click handler builds the same `InsightActorsQuery`
 *  as the legacy ActionsPie. Both call `datasetToActorsQuery` — ActionsPie passes a `GraphDataset`
 *  whose `breakdownValues` / `compareLabels` arrays carry one entry per slice plus the slice
 *  `index`, while the hog-charts path passes a one-slice dataset assembled from the source
 *  `IndexedTrendResult` (no `index` needed because the breakdown is already singular).
 *  This test pins that the resulting query objects are deeply equal across both call shapes. */
describe('persons modal parity between ActionsPie and TrendsPieChart', () => {
    const querySource: InsightActorsQuery['source'] = {
        kind: NodeKind.TrendsQuery,
        series: [{ kind: NodeKind.EventsNode, event: '$pageview' }],
        dateRange: { date_from: '-7d' },
    } as unknown as InsightActorsQuery['source']

    const action: ActionFilter = { id: 99, math: 'total', order: 2 } as unknown as ActionFilter

    const indexedResults: IndexedTrendResult[] = [
        {
            id: 0,
            seriesIndex: 0,
            colorIndex: 0,
            label: 'Chrome',
            aggregated_value: 100,
            data: [100],
            days: [],
            labels: [],
            count: 100,
            action,
            breakdown_value: 'chrome',
            compare_label: 'current',
        } as IndexedTrendResult,
        {
            id: 1,
            seriesIndex: 1,
            colorIndex: 1,
            label: 'Safari',
            aggregated_value: 50,
            data: [50],
            days: [],
            labels: [],
            count: 50,
            action,
            breakdown_value: 'safari',
            compare_label: 'current',
        } as IndexedTrendResult,
    ]

    // Build the input ActionsPie passes to datasetToActorsQuery.
    function legacyActionsPieDataset(): Pick<
        GraphDataset,
        'action' | 'breakdownValues' | 'compareLabels' | 'breakdown_value' | 'compare_label'
    > {
        return {
            action,
            breakdownValues: indexedResults.map((r) => r.breakdown_value),
            compareLabels: indexedResults.map((r) => r.compare_label),
        }
    }

    // Build the input the hog-charts TrendsPieChart passes to datasetToActorsQuery — single slice.
    function newPieDatasetForSlice(
        slice: IndexedTrendResult
    ): Pick<GraphDataset, 'action' | 'breakdown_value' | 'compare_label'> {
        return {
            action: slice.action,
            breakdown_value: slice.breakdown_value,
            compare_label: slice.compare_label,
        }
    }

    it('produces an identical query for a slice', () => {
        const legacyQuery = datasetToActorsQuery({
            dataset: legacyActionsPieDataset(),
            query: querySource,
            index: 0,
        })
        const newQuery = datasetToActorsQuery({
            dataset: newPieDatasetForSlice(indexedResults[0]),
            query: querySource,
        })
        expect(newQuery).toEqual(legacyQuery)
    })
})
