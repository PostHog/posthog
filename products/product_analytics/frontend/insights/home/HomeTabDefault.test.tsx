jest.unmock('lib/utils/concurrencyController')

import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import '@testing-library/jest-dom'

import { act, cleanup, render, screen, waitFor, within } from '@testing-library/react'
import { expectLogic } from 'kea-test-utils'

import { ensureJsdom } from '@posthog/quill-charts/testing'

import { promiseResolveReject } from 'lib/utils/async'
import { sampleDataStateLogic } from 'scenes/insights/EmptyStates/sampleDataStateLogic'
import { savedInsightsLogic } from 'scenes/saved-insights/savedInsightsLogic'
import { teamLogic } from 'scenes/teamLogic'

import trendsNumber from '~/mocks/fixtures/api/projects/team_id/insights/trendsNumber.json'
import { useMocks } from '~/mocks/jest'
import { dataNodeCollectionLogic } from '~/queries/nodes/DataNode/dataNodeCollectionLogic'
import { performQuery } from '~/queries/query'
import type { DataNode } from '~/queries/schema/schema-general'
import { isInsightQueryNode, isRetentionQuery, isTrendsQuery } from '~/queries/utils'
import { initKeaTests } from '~/test/init'
import { ChartDisplayType } from '~/types'

import { dataWarehouseSetupLogic } from 'products/data_warehouse/frontend/emptyState/dataWarehouseSetupLogic'

import { HomeTabDefault } from './HomeTabDefault'
import { homeTabDefaultLogic } from './homeTabDefaultLogic'
import { getHomeTabStatQueries } from './homeTabDefaultTiles'
import { homeTabDataCollectionId } from './homeTabQueryKeys'
import { HomeTabStatTile } from './HomeTabStatTile'

jest.mock('~/queries/query', () => ({
    ...jest.requireActual('~/queries/query'),
    performQuery: jest.fn(),
}))
jest.mock('~/queries/nodes/InsightViz/InsightVizDisplay', () => ({
    InsightVizDisplay: () => <div />,
}))

const mockedQuery = jest.mocked(performQuery)

describe('HomeTabDefault query reuse', () => {
    beforeEach(() => {
        initKeaTests()
        savedInsightsLogic.mount()
        mockedQuery.mockImplementation(async (query) => ({
            results: [
                {
                    ...trendsNumber.result[0],
                    aggregated_value: isInsightQueryNode(query) && query.dateRange?.date_from !== '-7d' ? 20 : 10,
                },
            ],
        }))
    })

    afterEach(() => {
        cleanup()
        savedInsightsLogic.unmount()
    })

    it.each([
        ['-30d', 28],
        ['-24h', 29],
    ] as const)('reuses loaded queries on return before and after changing to %s', async (dateFrom, queryCount) => {
        const { rerender } = render(<HomeTabDefault />)
        const collection = dataNodeCollectionLogic({ key: homeTabDataCollectionId(teamLogic.values.currentTeamId) })

        await waitFor(() => expect(mockedQuery).toHaveBeenCalledTimes(14))
        await waitFor(() => expect(collection.values.areAnyLoading).toBe(false))
        expect(
            within(screen.getByLabelText('Active users', { selector: 'button' })).getByText('10')
        ).toBeInTheDocument()

        await act(async () => rerender(<div>Another tab</div>))
        expect(savedInsightsLogic.isMounted()).toBe(true)
        await act(async () => rerender(<HomeTabDefault />))

        expect(mockedQuery).toHaveBeenCalledTimes(14)
        expect(
            within(screen.getByLabelText('Active users', { selector: 'button' })).getByText('10')
        ).toBeInTheDocument()

        await act(async () => homeTabDefaultLogic.actions.setDates(dateFrom, null))
        await waitFor(() => expect(mockedQuery).toHaveBeenCalledTimes(queryCount))
        await waitFor(() => expect(collection.values.areAnyLoading).toBe(false))

        expect(
            mockedQuery.mock.calls
                .slice(14)
                .every(([query]) => isInsightQueryNode(query) && query.dateRange?.date_from === dateFrom)
        ).toBe(true)
        expect(
            within(screen.getByLabelText('Active users', { selector: 'button' })).getByText('20')
        ).toBeInTheDocument()
        await act(async () => rerender(<div>Another tab</div>))
        await act(async () => rerender(<HomeTabDefault />))
        expect(mockedQuery).toHaveBeenCalledTimes(queryCount)
        await waitFor(() => expect(collection.values.areAnyLoading).toBe(false))
    })

    it('loads totals and the primary chart, then the sparklines, then the charts below them', async () => {
        const response = { results: [{ ...trendsNumber.result[0], aggregated_value: 10 }] }
        const pendingTrend = promiseResolveReject<typeof response>()
        const isSparkline = (query: DataNode): boolean =>
            isTrendsQuery(query) && query.compareFilter?.compare === false && !query.trendsFilter
        const isLowerChart = (query: DataNode): boolean =>
            isRetentionQuery(query) || (isTrendsQuery(query) && !!query.breakdownFilter)
        mockedQuery.mockImplementation(async (query) => (isSparkline(query) ? pendingTrend.promise : response))
        const { container } = render(<HomeTabDefault />)
        const collection = dataNodeCollectionLogic({ key: homeTabDataCollectionId(teamLogic.values.currentTeamId) })
        try {
            await waitFor(() => expect(mockedQuery).toHaveBeenCalledTimes(7))
            for (const tile of container.querySelectorAll('[data-attr^="home-tab-metric-"]')) {
                expect(tile).toHaveAttribute('aria-busy', 'false')
            }
            const calls = mockedQuery.mock.calls.map(([query]) => query)
            expect(calls.slice(0, 6).some(isSparkline)).toBe(false)
            expect(isSparkline(calls[6])).toBe(true)
            expect(calls.some(isLowerChart)).toBe(false)
        } finally {
            pendingTrend.resolve(response)
            await waitFor(() => expect(collection.values.areAnyLoading).toBe(false))
        }
        expect(mockedQuery.mock.calls.slice(-5).every(([query]) => isLowerChart(query))).toBe(true)
    })

    it('hides old trend values when the new total loads before the new trend', async () => {
        ensureJsdom()
        const trendResponse = {
            results: [
                {
                    ...trendsNumber.result[0],
                    data: [2, 3, 5],
                    days: ['2026-06-01', '2026-06-02', '2026-06-03'],
                    aggregated_value: 10,
                },
            ],
        }
        let finishTrend!: (response: typeof trendResponse) => void
        const pendingTrend = new Promise<typeof trendResponse>((resolve) => {
            finishTrend = resolve
        })
        mockedQuery.mockImplementation(async (query) => {
            if (isTrendsQuery(query) && query.dateRange?.date_from === '-30d') {
                if (query.trendsFilter?.display !== ChartDisplayType.BoldNumber) {
                    return pendingTrend
                }
                return { results: [{ ...trendResponse.results[0], aggregated_value: 20 }] }
            }
            return trendResponse
        })
        const tile = (dateFrom: string): JSX.Element => (
            <HomeTabStatTile
                stat={getHomeTabStatQueries({ date_from: dateFrom }, false).find(({ key }) => key === 'sessions')!}
                compare={false}
                selected={false}
                onSelect={() => {}}
            />
        )
        const { container, rerender } = render(tile('-7d'))
        await waitFor(() => expect(container.querySelector('[data-attr="metric-sparkline"]')).not.toBeNull())
        await act(async () => rerender(tile('-30d')))
        await waitFor(() => expect(screen.getByText('20')).toBeInTheDocument())
        expect(container.querySelector('[data-attr="metric-sparkline"]')).toBeNull()
        await act(async () => finishTrend(trendResponse))
        await waitFor(() => expect(container.querySelector('[data-attr="metric-sparkline"]')).not.toBeNull())
    })

    it('shows the metric details and opens the same total in the insight editor, outside the tile button', async () => {
        mockedQuery.mockImplementation(async () => ({
            results: [{ ...trendsNumber.result[0], aggregated_value: 10 }],
            last_refresh: new Date().toISOString(),
        }))
        render(
            <HomeTabStatTile
                stat={getHomeTabStatQueries({ date_from: '-7d' }, true).find(({ key }) => key === 'sessions')!}
                compare
                selected={false}
                onSelect={() => {}}
            />
        )
        const tileButton = screen.getByLabelText('Sessions', { selector: 'button' })
        await waitFor(() => expect(within(tileButton).getByText('10')).toBeInTheDocument())

        const info = document.querySelector('[data-attr="card-meta-info"]') as HTMLElement
        const more = screen.getByLabelText('more')
        expect(tileButton.contains(info) || tileButton.contains(more)).toBe(false)

        await act(async () => info.click())
        expect(await screen.findByText('Last 7 days')).toBeInTheDocument()
        expect(screen.getByLabelText('Last computed time')).toBeInTheDocument()

        await act(async () => more.click())
        const explore = (await screen.findByText('Explore')).closest('a')!
        const exploreQuery = JSON.parse(new URLSearchParams(new URL(explore.href).hash.slice(1)).get('q')!)
        expect(exploreQuery).toMatchObject({
            source: {
                dateRange: { date_from: '-7d' },
                compareFilter: { compare: true },
                trendsFilter: { display: ChartDisplayType.BoldNumber },
            },
        })
    })

    it('replaces sample metrics and charts with live queries when the project starts receiving events', async () => {
        ensureJsdom()
        teamLogic.actions.loadCurrentTeamSuccess({ ...MOCK_DEFAULT_TEAM, ingested_event: false, is_demo: false })
        // Sample data waits for warehouse detection, and live queries run until it settles.
        sampleDataStateLogic.mount()
        await expectLogic(dataWarehouseSetupLogic).toDispatchActions(['detectStatusSuccess'])
        const { container } = render(<HomeTabDefault />)

        await waitFor(() =>
            expect(container.querySelectorAll('[data-attr="insight-sample-data-tag"]')).toHaveLength(11)
        )
        for (const tile of container.querySelectorAll('[data-attr^="home-tab-metric-"]')) {
            expect(tile).toHaveAttribute('aria-busy', 'false')
            expect(tile.querySelector('[data-attr="metric-sparkline"]')).not.toBeNull()
        }
        expect(mockedQuery).not.toHaveBeenCalled()
        expect(screen.queryByText('No previous period data')).not.toBeInTheDocument()

        await act(async () => homeTabDefaultLogic.actions.setSelectedMetric('sessions'))
        expect(mockedQuery).not.toHaveBeenCalled()

        await act(async () => {
            teamLogic.actions.loadCurrentTeamSuccess({ ...MOCK_DEFAULT_TEAM, ingested_event: true, is_demo: false })
        })

        await waitFor(() => expect(mockedQuery).toHaveBeenCalledTimes(14))
        expect(container.querySelector('[data-attr="insight-sample-data-tag"]')).toBeNull()
        await waitFor(() =>
            expect(
                within(screen.getByLabelText('Sessions', { selector: 'button' })).getByText('10')
            ).toBeInTheDocument()
        )
    })

    it('runs live queries once warehouse detection finds data for a project without events', async () => {
        useMocks({ get: { '/api/projects/:team_id/external_data_sources/exists/': { exists: true } } })
        teamLogic.actions.loadCurrentTeamSuccess({ ...MOCK_DEFAULT_TEAM, ingested_event: false, is_demo: false })
        const { container } = render(<HomeTabDefault />)

        await waitFor(() => expect(mockedQuery).toHaveBeenCalledTimes(14))
        await waitFor(() =>
            expect(
                within(screen.getByLabelText('Active users', { selector: 'button' })).getByText('10')
            ).toBeInTheDocument()
        )
        expect(container.querySelector('[data-attr="insight-sample-data-tag"]')).toBeNull()
    })
})
