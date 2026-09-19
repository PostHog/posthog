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

/** The response the stubbed `Query` reports; null means the query must never mount. */
let mockQueryResponse: Record<string, unknown> | null = null

jest.mock('~/queries/Query/Query', () => {
    const { useEffect } = require('react')
    return {
        Query: ({ context }: { context?: { onQueryData?: (response: unknown) => void } }) => {
            useEffect(() => {
                context?.onQueryData?.(mockQueryResponse)
            }, [context])
            if (!mockQueryResponse) {
                throw new Error('The collapsed visualization must not mount its query')
            }
            return null
        },
    }
})

const TRENDS_CONTENT: VisualizationArtifactContent = {
    content_type: ArtifactContentType.Visualization,
    query: {
        kind: NodeKind.TrendsQuery,
        series: [{ kind: NodeKind.EventsNode, event: '$pageview' }],
    },
}

describe('VisualizationWidget', () => {
    beforeEach(() => {
        initKeaTests()
        router.actions.push('/project/997/insights/current')
        mockQueryResponse = null
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

    // A thread of empty results used to stack one chart-sized box of nothing per attempt.
    it.each([
        ['matched nothing', [], true],
        ['has rows', [{ count: 3 }], false],
    ])('collapses a card whose query %s', async (_name, results, expectedNotice) => {
        mockQueryResponse = { results }
        render(
            <Provider>
                <VisualizationWidget content={TRENDS_CONTENT} embedded />
            </Provider>
        )
        await waitFor(() => {
            expect(!!screen.queryByText('No data matched this query.')).toBe(expectedNotice)
        })
    })
})
