import { initKeaTests } from '~/test/init'
import { ChartDisplayType } from '~/types'

import { llmAnalyticsLogic } from './llmAnalyticsLogic'

describe('llmAnalyticsLogic', () => {
    let logic: ReturnType<typeof llmAnalyticsLogic.build>

    beforeEach(() => {
        initKeaTests()
        logic = llmAnalyticsLogic()
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
    })

    describe('tiles configuration', () => {
        it('should have explicitDate set to true for aggregate display tiles', () => {
            const tiles = logic.values.tiles

            // Find the aggregate display tiles
            const totalCostTile = tiles.find((t) => t.title === 'Total cost (USD)')
            const costByModelTile = tiles.find((t) => t.title === 'Cost by model (USD)')
            const generationsByStatusTile = tiles.find((t) => t.title === 'Generations by HTTP status')

            // Verify Total cost tile
            expect(totalCostTile).not.toBeUndefined()
            expect(totalCostTile?.query.dateRange?.explicitDate).toBe(true)
            expect(totalCostTile?.query.trendsFilter?.display).toBe(ChartDisplayType.BoldNumber)

            // Verify Cost by model tile
            expect(costByModelTile).not.toBeUndefined()
            expect(costByModelTile?.query.dateRange?.explicitDate).toBe(true)
            expect(costByModelTile?.query.trendsFilter?.display).toBe(ChartDisplayType.ActionsBarValue)

            // Verify Generations by HTTP status tile
            expect(generationsByStatusTile).not.toBeUndefined()
            expect(generationsByStatusTile?.query.dateRange?.explicitDate).toBe(true)
            expect(generationsByStatusTile?.query.trendsFilter?.display).toBe(ChartDisplayType.ActionsBarValue)
        })

        it('should NOT have explicitDate set for time-series display tiles', () => {
            const tiles = logic.values.tiles

            // Find the time-series tiles
            const tracesTile = tiles.find((t) => t.title === 'Traces')
            const usersTile = tiles.find((t) => t.title === 'Generative AI users')
            const costPerUserTile = tiles.find((t) => t.title === 'Cost per user (USD)')
            const generationCallsTile = tiles.find((t) => t.title === 'Generation calls')
            const latencyTile = tiles.find((t) => t.title === 'Generation latency by model (median)')

            // Verify Traces tile
            expect(tracesTile).not.toBeUndefined()
            expect(tracesTile?.query.dateRange?.explicitDate).toBeUndefined()
            expect(tracesTile?.query.trendsFilter?.display).toBeUndefined()

            // Verify Generative AI users tile
            expect(usersTile).not.toBeUndefined()
            expect(usersTile?.query.dateRange?.explicitDate).toBeUndefined()
            expect(usersTile?.query.trendsFilter?.display).toBeUndefined()

            // Verify Cost per user tile
            expect(costPerUserTile).not.toBeUndefined()
            expect(costPerUserTile?.query.dateRange?.explicitDate).toBeUndefined()
            // Has formula but no specific display type
            expect(costPerUserTile?.query.trendsFilter?.formula).not.toBeUndefined()
            expect(costPerUserTile?.query.trendsFilter?.display).toBeUndefined()

            // Verify Generation calls tile
            expect(generationCallsTile).not.toBeUndefined()
            expect(generationCallsTile?.query.dateRange?.explicitDate).toBeUndefined()
            expect(generationCallsTile?.query.trendsFilter?.display).toBeUndefined()

            // Verify Generation latency tile
            expect(latencyTile).not.toBeUndefined()
            expect(latencyTile?.query.dateRange?.explicitDate).toBeUndefined()
            expect(latencyTile?.query.trendsFilter?.display).toBeUndefined()
        })

        it('should have all 8 expected tiles', () => {
            const tiles = logic.values.tiles

            expect(tiles).toHaveLength(8)

            const expectedTitles = [
                'Traces',
                'Generative AI users',
                'Total cost (USD)',
                'Cost per user (USD)',
                'Cost by model (USD)',
                'Generation calls',
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

            // Aggregate displays
            const totalCost = tiles.find((t) => t.title === 'Total cost (USD)')
            expect(totalCost?.query.trendsFilter?.display).toBe(ChartDisplayType.BoldNumber)

            const costByModel = tiles.find((t) => t.title === 'Cost by model (USD)')
            expect(costByModel?.query.trendsFilter?.display).toBe(ChartDisplayType.ActionsBarValue)

            const generationsByStatus = tiles.find((t) => t.title === 'Generations by HTTP status')
            expect(generationsByStatus?.query.trendsFilter?.display).toBe(ChartDisplayType.ActionsBarValue)

            // Time-series displays (should not have display type, defaults to line graph)
            const timeSeries = [
                'Traces',
                'Generative AI users',
                'Cost per user (USD)',
                'Generation calls',
                'Generation latency by model (median)',
            ]

            timeSeries.forEach((title) => {
                const tile = tiles.find((t) => t.title === title)
                expect(tile?.query.trendsFilter?.display).toBeUndefined()
            })
        })
    })
})
