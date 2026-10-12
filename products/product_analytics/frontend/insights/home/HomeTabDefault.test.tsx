import '@testing-library/jest-dom'

import { act, cleanup, render, screen, waitFor, within } from '@testing-library/react'

import { HomeTabDefault } from 'scenes/saved-insights/HomeTabDefault'
import { homeTabDefaultLogic } from 'scenes/saved-insights/homeTabDefaultLogic'
import { savedInsightsLogic } from 'scenes/saved-insights/savedInsightsLogic'
import { teamLogic } from 'scenes/teamLogic'

import trendsNumber from '~/mocks/fixtures/api/projects/team_id/insights/trendsNumber.json'
import { dataNodeCollectionLogic } from '~/queries/nodes/DataNode/dataNodeCollectionLogic'
import { performQuery } from '~/queries/query'
import { isInsightQueryNode } from '~/queries/utils'
import { initKeaTests } from '~/test/init'

import { homeTabDataCollectionId } from './homeTabQueryKeys'

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
                    aggregated_value: isInsightQueryNode(query) && query.dateRange?.date_from === '-30d' ? 20 : 10,
                },
            ],
        }))
    })

    afterEach(() => {
        cleanup()
        savedInsightsLogic.unmount()
    })

    it('reuses loaded queries on return and fetches new results when the range changes', async () => {
        const { rerender } = render(<HomeTabDefault />)
        const collection = dataNodeCollectionLogic({ key: homeTabDataCollectionId(teamLogic.values.currentTeamId) })

        await waitFor(() => expect(mockedQuery).toHaveBeenCalledTimes(11))
        await waitFor(() => expect(collection.values.areAnyLoading).toBe(false))
        expect(
            within(screen.getByLabelText('Active users', { selector: 'button' })).getByText('10')
        ).toBeInTheDocument()

        await act(async () => rerender(<div>Another tab</div>))
        expect(savedInsightsLogic.isMounted()).toBe(true)
        await act(async () => rerender(<HomeTabDefault />))

        expect(mockedQuery).toHaveBeenCalledTimes(11)
        expect(
            within(screen.getByLabelText('Active users', { selector: 'button' })).getByText('10')
        ).toBeInTheDocument()

        await act(async () => homeTabDefaultLogic.actions.setDates('-30d', null))
        await waitFor(() => expect(mockedQuery).toHaveBeenCalledTimes(22))
        await waitFor(() => expect(collection.values.areAnyLoading).toBe(false))

        expect(
            mockedQuery.mock.calls
                .slice(11)
                .every(([query]) => isInsightQueryNode(query) && query.dateRange?.date_from === '-30d')
        ).toBe(true)
        expect(
            within(screen.getByLabelText('Active users', { selector: 'button' })).getByText('20')
        ).toBeInTheDocument()
    })
})
