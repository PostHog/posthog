import { ChartDisplayType } from '~/types'

import { getChartDisplayOptions } from './chartDisplayOptions'

describe('getChartDisplayOptions', () => {
    it('disables chart types the insight cannot render and says why', () => {
        const options = getChartDisplayOptions({
            isTrends: true,
            hasSingleSeriesOutput: false,
            hasTrendsFormula: true,
            breakdown: 'browser',
            boxPlotMissingProperty: true,
            hasMetricInsight: false,
        })
        const optionsByDisplay = new Map(
            options.flatMap((group) => group.options).map((option) => [option.display, option])
        )

        expect(optionsByDisplay.has(ChartDisplayType.Metric)).toBe(false)
        expect(optionsByDisplay.get(ChartDisplayType.BoldNumber)?.disabledReason).toBe(
            'This type currently only supports insights with one series, and this insight has multiple series.'
        )
        expect(optionsByDisplay.get(ChartDisplayType.BoxPlot)?.disabledReason).toBe(
            'Select a numeric property to use a box plot.'
        )
        expect(optionsByDisplay.get(ChartDisplayType.WorldMap)?.disabledReason).toBe(
            "This type isn't available, because it doesn't support formulas."
        )
        expect(optionsByDisplay.get(ChartDisplayType.ActionsLineGraph)?.disabledReason).toBeUndefined()
    })
})
