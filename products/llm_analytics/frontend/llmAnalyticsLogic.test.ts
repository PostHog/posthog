import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { urls } from 'scenes/urls'

import { NON_TIME_SERIES_DISPLAY_TYPES } from '~/lib/constants'
import { initKeaTests } from '~/test/init'
import { ChartDisplayType, PropertyFilterType, PropertyOperator } from '~/types'

import { sceneLogic } from '../../../frontend/src/scenes/sceneLogic'
import { llmAnalyticsLogic } from './llmAnalyticsLogic'

describe('llmAnalyticsLogic', () => {
    let logic: ReturnType<typeof llmAnalyticsLogic.build>

    beforeEach(() => {
        initKeaTests()
        sceneLogic.mount()
        router.actions.push(urls.llmAnalyticsTraces())
        logic = llmAnalyticsLogic({ tabId: sceneLogic.values.activeTabId || '' })
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
    })

    describe('tiles configuration', () => {
        it('should have explicitDate set to true for aggregate display tiles', () => {
            const tiles = logic.values.tiles

            // Filter tiles that have non-time-series display types
            const nonTimeSeriesTiles = tiles.filter(
                (tile) =>
                    tile.query.trendsFilter?.display &&
                    NON_TIME_SERIES_DISPLAY_TYPES.includes(tile.query.trendsFilter.display)
            )

            // Should have exactly 3 non-time-series tiles
            expect(nonTimeSeriesTiles).toHaveLength(3)

            // All non-time-series tiles should have explicitDate set to true
            nonTimeSeriesTiles.forEach((tile) => {
                expect(tile.query.dateRange?.explicitDate).toBe(true)
            })

            // Verify expected display types are present
            const displayTypes = nonTimeSeriesTiles.map((tile) => tile.query.trendsFilter?.display)
            expect(displayTypes).toContain(ChartDisplayType.BoldNumber)
            expect(displayTypes).toContain(ChartDisplayType.ActionsBarValue)

            // Count occurrences of ActionsBarValue (should be 2)
            const actionsBarValueCount = displayTypes.filter((d) => d === ChartDisplayType.ActionsBarValue).length
            expect(actionsBarValueCount).toBe(2)
        })

        it('should NOT have explicitDate set for time-series display tiles', () => {
            const tiles = logic.values.tiles

            // Filter tiles that are time-series (no display type or not in NON_TIME_SERIES_DISPLAY_TYPES)
            const timeSeriesTiles = tiles.filter(
                (tile) =>
                    !tile.query.trendsFilter?.display ||
                    !NON_TIME_SERIES_DISPLAY_TYPES.includes(tile.query.trendsFilter.display)
            )

            // Should have exactly 6 time-series tiles
            expect(timeSeriesTiles).toHaveLength(6)

            // All time-series tiles should NOT have explicitDate set
            timeSeriesTiles.forEach((tile) => {
                expect(tile.query.dateRange?.explicitDate).toBeUndefined()
            })

            // All time-series tiles should have undefined display type
            timeSeriesTiles.forEach((tile) => {
                expect(tile.query.trendsFilter?.display).toBeUndefined()
            })

            // Verify one of them has a formula (Cost per user)
            const tilesWithFormula = timeSeriesTiles.filter((tile) => tile.query.trendsFilter?.formula)
            expect(tilesWithFormula).toHaveLength(1)
            expect(tilesWithFormula[0].query.trendsFilter?.formula).toBe('A / B')
        })

        it('should have all 9 expected tiles', () => {
            const tiles = logic.values.tiles

            expect(tiles).toHaveLength(9)

            const expectedTitles = [
                'Traces',
                'Generative AI users',
                'Total cost (USD)',
                'Cost per user (USD)',
                'Cost by model (USD)',
                'Generation calls',
                'AI Errors',
                'Generation latency by model (median)',
                'Generations by HTTP status',
            ]

            const actualTitles = tiles.map((t) => t.title)
            expectedTitles.forEach((title) => {
                expect(actualTitles).toContain(title)
            })
        })

        it('should pass dateRange values from dashboardDateFilter to all tiles', () => {
            // Set specific date filter values
            logic.actions.setDates('-7d', null)

            const tiles = logic.values.tiles
            const { dateFrom, dateTo } = logic.values.dashboardDateFilter

            // All tiles should have the same date range
            tiles.forEach((tile) => {
                expect(tile.query.dateRange?.date_from).toBe(dateFrom)
                expect(tile.query.dateRange?.date_to).toBe(dateTo)
            })
        })

        it('should maintain correct display types for visualization', () => {
            const tiles = logic.values.tiles

            // Non-time-series tiles grouped by display type
            const boldNumberTiles = tiles.filter(
                (tile) => tile.query.trendsFilter?.display === ChartDisplayType.BoldNumber
            )
            const actionsBarValueTiles = tiles.filter(
                (tile) => tile.query.trendsFilter?.display === ChartDisplayType.ActionsBarValue
            )

            // Verify counts
            expect(boldNumberTiles).toHaveLength(1)
            expect(actionsBarValueTiles).toHaveLength(2)

            // Verify all non-time-series tiles are in NON_TIME_SERIES_DISPLAY_TYPES
            const allNonTimeSeriesTiles = [...boldNumberTiles, ...actionsBarValueTiles]
            allNonTimeSeriesTiles.forEach((tile) => {
                expect(NON_TIME_SERIES_DISPLAY_TYPES).toContain(tile.query.trendsFilter?.display)
            })

            // Time-series tiles (undefined display type)
            const timeSeriesTiles = tiles.filter((tile) => tile.query.trendsFilter?.display === undefined)
            expect(timeSeriesTiles).toHaveLength(6)

            // Verify all tiles are accounted for
            expect(tiles).toHaveLength(9)
            expect(boldNumberTiles.length + actionsBarValueTiles.length + timeSeriesTiles.length).toBe(9)
        })
    })

    it('should handle URL parameters correctly', () => {
        const filters = [
            {
                type: 'event',
                key: 'browser',
                value: 'Chrome',
                operator: 'exact',
            },
        ]

        // Navigate with various parameters
        router.actions.push(urls.llmAnalyticsTraces(), {
            filters: filters,
            date_from: '-14d',
            date_to: '-1d',
            filter_test_accounts: 'true',
        })

        // Should apply all parameters
        expectLogic(logic).toMatchValues({
            propertyFilters: filters,
            dateFilter: {
                dateFrom: '-14d',
                dateTo: '-1d',
            },
            shouldFilterTestAccounts: true,
        })
    })

    it('should reset filters when switching tabs without params', () => {
        // Set some filters first
        logic.actions.setPropertyFilters([
            {
                type: PropertyFilterType.Event,
                key: 'test',
                value: 'value',
                operator: PropertyOperator.Exact,
            },
        ])
        logic.actions.setDates('-30d', '-1d')
        logic.actions.setShouldFilterTestAccounts(true)

        // Navigate to another tab without params
        router.actions.push(urls.llmAnalyticsGenerations())

        // Should reset to defaults
        expectLogic(logic).toMatchValues({
            propertyFilters: [],
            dateFilter: {
                dateFrom: '-1d',
                dateTo: null,
            },
            shouldFilterTestAccounts: false,
        })
    })
})
