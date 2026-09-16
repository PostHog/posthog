import { ChartDisplayType } from '~/types'

import type { ChartDisplayOptionEligibility } from './chartDisplayOptions'
import { getChartDisplayOptions } from './chartDisplayOptions'

const RENDERS_EVERYTHING: ChartDisplayOptionEligibility = {
    isTrends: true,
    hasSingleSeriesOutput: true,
    hasTrendsFormula: false,
    boxPlotMissingProperty: false,
    hasMetricInsight: false,
}

function disabledReasons(eligibility: ChartDisplayOptionEligibility): Map<ChartDisplayType, string | undefined> {
    return new Map(
        getChartDisplayOptions(eligibility)
            .flatMap((group) => group.options)
            .map((option) => [option.display, option.disabledReason])
    )
}

describe('getChartDisplayOptions', () => {
    it.each([
        [
            'not Trends',
            { ...RENDERS_EVERYTHING, isTrends: false },
            ChartDisplayType.SlopeGraph,
            'This type is only available in Trends.',
        ],
        [
            'multiple series',
            { ...RENDERS_EVERYTHING, hasSingleSeriesOutput: false },
            ChartDisplayType.BoldNumber,
            'This type currently only supports insights with one series, and this insight has multiple series.',
        ],
        [
            'box plot without a numeric property',
            { ...RENDERS_EVERYTHING, boxPlotMissingProperty: true },
            ChartDisplayType.BoxPlot,
            'Select a numeric property to use a box plot.',
        ],
        [
            'world map with a formula',
            { ...RENDERS_EVERYTHING, hasTrendsFormula: true },
            ChartDisplayType.WorldMap,
            "This type isn't available, because it doesn't support formulas.",
        ],
        [
            'world map with a breakdown other than country',
            { ...RENDERS_EVERYTHING, breakdown: 'browser' },
            ChartDisplayType.WorldMap,
            "This type isn't available, because there's a breakdown other than by Country Code or Country Name properties.",
        ],
        [
            'world map with two breakdowns',
            {
                ...RENDERS_EVERYTHING,
                breakdowns: [{ property: '$geoip_country_code' }, { property: 'browser' }],
            },
            ChartDisplayType.WorldMap,
            "This type isn't available, because there's a breakdown other than by Country Code or Country Name properties.",
        ],
        [
            'world map with one country breakdown',
            { ...RENDERS_EVERYTHING, breakdowns: [{ property: '$geoip_country_code' }] },
            ChartDisplayType.WorldMap,
            undefined,
        ],
        ['nothing in the way', RENDERS_EVERYTHING, ChartDisplayType.ActionsLineGraph, undefined],
    ])('says why %s disables a chart type', (_case, eligibility, display, disabledReason) => {
        const reasons = disabledReasons(eligibility)

        expect(reasons.has(display)).toBe(true)
        expect(reasons.get(display)).toBe(disabledReason)
    })

    it.each([
        [true, true],
        [false, false],
    ])('offers the metric chart type only behind its flag (%s)', (hasMetricInsight, isOffered) => {
        expect(disabledReasons({ ...RENDERS_EVERYTHING, hasMetricInsight }).has(ChartDisplayType.Metric)).toBe(
            isOffered
        )
    })
})
