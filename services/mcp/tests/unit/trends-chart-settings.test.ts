import { describe, expect, it } from 'vitest'

import {
    chartConfigFromTrendsFilter,
    DEFAULT_CHART_CONFIG,
    defaultChartType,
    isBarFamily,
    resolveChartView,
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
                showConfidenceIntervals: true,
                confidenceLevel: 90,
                showPercentStackView: true,
                aggregationAxisFormat: 'duration',
            }
            expect(chartConfigFromTrendsFilter(trendsFilter)).toEqual({
                showValueLabels: true,
                showTrendLine: true,
                showConfidenceIntervals: true,
                confidenceLevel: 90,
                percentStack: true,
                yUnit: 'duration',
            })
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

    describe('resolveChartView', () => {
        it.each([
            [0, false],
            [1, false],
            [2, true],
            [7, true],
        ] as const)('slope is available with %i labels: %s', (labelCount, slopeAvailable) => {
            expect(resolveChartView('line', labelCount).slopeAvailable).toBe(slopeAvailable)
        })

        it('falls slope back to line when there are fewer than two points', () => {
            expect(resolveChartView('slope', 1).effectiveType).toBe('line')
            expect(resolveChartView('slope', 0).effectiveType).toBe('line')
        })

        it('keeps slope when there are at least two points', () => {
            expect(resolveChartView('slope', 2).effectiveType).toBe('slope')
        })

        it.each(['line', 'area', 'bar', 'stacked-bar'] as const)('passes %s through unchanged', (chartType) => {
            expect(resolveChartView(chartType, 7).effectiveType).toBe(chartType)
        })
    })
})
