import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { Provider } from 'kea'
import { router } from 'kea-router'

import { useMocks } from '~/mocks/jest'
import { ArtifactContentType, VisualizationArtifactContent } from '~/queries/schema/schema-assistant-messages'
import { NodeKind } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import { PropertyFilterType, PropertyOperator } from '~/types'

import { VisualizationWidget } from './VisualizationWidget'

jest.mock('~/queries/Query/Query', () => ({
    Query: () => {
        throw new Error('The collapsed visualization must not mount its query')
    },
}))

describe('VisualizationWidget', () => {
    beforeEach(() => {
        initKeaTests()
        router.actions.push('/project/997/insights/current')
    })

    afterEach(cleanup)

    it('resolves a collapsed AI definition without loading the chart or full cohort list', async () => {
        const list = jest.fn(() => ({ count: 0, results: [] }))
        const detail = jest.fn(({ params }) => ({
            id: Number(params.id),
            name: params.id === '3000' ? 'Returning visitors' : 'Paid visitors',
            groups: [],
            filters: { properties: { type: 'AND', values: [] } },
        }))
        useMocks({
            get: {
                '/api/projects/:team/cohorts/': list,
                '/api/projects/:team/cohorts/:id/': detail,
            },
        })
        const content: VisualizationArtifactContent = {
            content_type: ArtifactContentType.Visualization,
            query: {
                kind: NodeKind.TrendsQuery,
                series: [{ kind: NodeKind.EventsNode, event: '$pageview' }],
                properties: [
                    { type: PropertyFilterType.Cohort, key: 'id', value: 3000, operator: PropertyOperator.In },
                ],
                breakdownFilter: { breakdown_type: 'cohort', breakdown: [3001] },
            },
        }
        render(
            <Provider>
                <VisualizationWidget content={content} isCollapsed embedded />
            </Provider>
        )
        expect(detail).not.toHaveBeenCalled()
        fireEvent.click(screen.getByText('Trends'))
        await waitFor(() => {
            expect(screen.getByText(/Returning visitors/)).toBeInTheDocument()
            expect(screen.getByText(/Paid visitors/)).toBeInTheDocument()
        })
        fireEvent.click(screen.getByText('Trends'))
        fireEvent.click(screen.getByText('Trends'))
        expect(detail).toHaveBeenCalledTimes(2)
        expect(list).not.toHaveBeenCalled()
    })
})
