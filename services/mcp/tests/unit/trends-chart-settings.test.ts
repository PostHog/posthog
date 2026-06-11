import { describe, expect, it } from 'vitest'

import {
    chartConfigFromTrendsFilter,
    DEFAULT_CHART_CONFIG,
    defaultChartType,
    isBarFamily,
    supportsPercentStack,
} from '../../src/ui-apps/components/chartSettingsConfig'
import type { ChartDisplayType, TrendsFilter } from '../../src/ui-apps/components/types'

describe('trends chart settings', () => {
    describe('chartConfigFromTrendsFilter', () => {
        it('returns defaults when there is no trendsFilter', () => {
            expect(chartConfigFromTrendsFilter(undefined)).toEqual(DEFAULT_CHART_CONFIG)
        })

        it('seeds every field from a fully populated trendsFilter', () => {
            const trendsFilter: TrendsFilter = {
                showValuesOnSeries: true,
                showTrendLines: true,
                showMovingAverage: true,
                movingAverageIntervals: 14,
                showConfidenceIntervals: true,
                confidenceLevel: 90,
                showPercentStackView: true,
                aggregationAxisFormat: 'duration',
            }
            expect(chartConfigFromTrendsFilter(trendsFilter)).toEqual({
                showValueLabels: true,
                showTrendLine: true,
                showMovingAverage: true,
                movingAverageIntervals: 14,
                showConfidenceIntervals: true,
                confidenceLevel: 90,
                percentStack: true,
                yUnit: 'duration',
            })
        })

        it.each([[undefined], [0]])('falls back to a 7-interval moving average window for %s', (intervals) => {
            const config = chartConfigFromTrendsFilter({ movingAverageIntervals: intervals })
            expect(config.movingAverageIntervals).toBe(7)
        })

        it('ignores unrelated trendsFilter fields', () => {
            expect(chartConfigFromTrendsFilter({ display: 'ActionsBar', showLegend: true })).toEqual(
                DEFAULT_CHART_CONFIG
            )
        })
    })

    describe('defaultChartType', () => {
        it.each([
            ['ActionsLineGraph', 'line'],
            ['ActionsLineGraphCumulative', 'line'],
            ['ActionsAreaGraph', 'area'],
            ['ActionsBar', 'stacked-bar'],
            ['ActionsStackedBar', 'stacked-bar'],
            ['ActionsUnstackedBar', 'bar'],
            ['ActionsPie', 'line'],
            ['SlopeGraph', 'slope'],
        ] as Array<[ChartDisplayType, string]>)('maps %s to %s', (displayType, expected) => {
            expect(defaultChartType(displayType)).toBe(expected)
        })
    })

    describe('chart type predicates', () => {
        it.each([
            ['line', false, false],
            ['area', false, true],
            ['bar', true, false],
            ['stacked-bar', true, true],
            ['slope', false, false],
        ] as const)('%s: isBarFamily=%s, supportsPercentStack=%s', (chartType, barFamily, percentStack) => {
            expect(isBarFamily(chartType)).toBe(barFamily)
            expect(supportsPercentStack(chartType)).toBe(percentStack)
        })
    })
})
