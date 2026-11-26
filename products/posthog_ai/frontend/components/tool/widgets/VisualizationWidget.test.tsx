import '@testing-library/jest-dom'

import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { Provider } from 'kea'
import { router } from 'kea-router'
import {
    mockAllIsIntersecting,
    setupIntersectionMocking,
    resetIntersectionMocking,
} from 'react-intersection-observer/test-utils'

import { useMocks } from '~/mocks/jest'
import { ArtifactContentType, VisualizationArtifactContent } from '~/queries/schema/schema-assistant-messages'
import { NodeKind } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import { PropertyFilterType, PropertyOperator } from '~/types'

import { VisualizationWidget } from './VisualizationWidget'

jest.mock('~/queries/Query/Query', () => ({
    Query: () => <div data-attr="chart" />,
}))

describe('VisualizationWidget', () => {
    beforeEach(() => {
        setupIntersectionMocking(jest.fn)
        initKeaTests()
        router.actions.push('/project/997/insights/current')
    })

    afterEach(() => {
        cleanup()
        resetIntersectionMocking()
    })

    it('mounts a chart only when near the viewport and keeps it mounted after scrolling away', () => {
        render(
            <Provider>
                <VisualizationWidget
                    content={{
                        content_type: ArtifactContentType.Visualization,
                        query: {
                            kind: NodeKind.TrendsQuery,
                            series: [{ kind: NodeKind.EventsNode, event: '$pageview' }],
                        },
                    }}
                />
            </Provider>
        )
        expect(screen.queryByTestId('chart')).not.toBeInTheDocument()
        act(() => mockAllIsIntersecting(true))
        expect(screen.getByTestId('chart')).toBeInTheDocument()
        act(() => mockAllIsIntersecting(false))
        expect(screen.getByTestId('chart')).toBeInTheDocument()
    })

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
                <VisualizationWidget content={content} isCollapsed />
            </Provider>
        )
        expect(screen.queryByTestId('chart')).not.toBeInTheDocument()
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
