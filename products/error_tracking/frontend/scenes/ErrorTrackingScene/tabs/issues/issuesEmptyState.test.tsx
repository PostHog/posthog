import '@testing-library/jest-dom'

import { cleanup, render, screen, waitFor } from '@testing-library/react'

import { useMocks } from '~/mocks/jest'
import { Query } from '~/queries/Query/Query'
import { DataTableNode, NodeKind } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import { AnyPropertyFilter, FilterLogicalOperator, PropertyFilterType, PropertyOperator } from '~/types'

let latestEmptyState: React.ReactNode = null
let latestLoading: boolean | undefined

jest.mock('lib/lemon-ui/LemonTable', () => ({
    ...jest.requireActual('lib/lemon-ui/LemonTable'),
    LemonTable: (props: { emptyState?: React.ReactNode; loading?: boolean }): null => {
        latestEmptyState = props.emptyState
        latestLoading = props.loading
        return null
    },
}))

function issuesQuery(filterValues: AnyPropertyFilter[] = []): DataTableNode {
    return {
        kind: NodeKind.DataTableNode,
        source: {
            kind: NodeKind.ErrorTrackingQuery,
            orderBy: 'last_seen',
            dateRange: {},
            volumeResolution: 0,
            filterGroup: {
                type: FilterLogicalOperator.And,
                values: [{ type: FilterLogicalOperator.And, values: filterValues }],
            },
            withAggregations: true,
            withFirstEvent: false,
        },
        columns: ['error', 'occurrences'],
    }
}

async function renderEmptyStateAfterLoad(query: DataTableNode): Promise<void> {
    render(<Query query={query} context={{ emptyStateHeading: 'No issues found' }} uniqueKey="issues-empty-state" />)
    await waitFor(() => {
        if (latestLoading !== false) {
            throw new Error('Expected the table to finish loading')
        }
    })
    // The mocked table never renders its emptyState prop, so render it on its own.
    cleanup()
    render(<>{latestEmptyState}</>)
}

describe('issues list empty state', () => {
    beforeEach(() => {
        useMocks({ post: { '/api/environments/:team_id/query/': [200, { results: [] }] } })
        initKeaTests()
        latestEmptyState = null
        latestLoading = undefined
    })

    afterEach(() => {
        cleanup()
        jest.clearAllMocks()
    })

    it('shows a retry error state when the load returns no response', async () => {
        // An invalid regex filter makes the query fail validation, so the load resolves to null
        // without ever reaching the server — the swallowed-failure path the fix targets.
        await renderEmptyStateAfterLoad(
            issuesQuery([
                {
                    type: PropertyFilterType.Event,
                    key: '$browser',
                    operator: PropertyOperator.Regex,
                    value: '(',
                },
            ])
        )

        expect(screen.getByText('Could not load issues')).toBeInTheDocument()
        expect(screen.queryByText('No issues found')).not.toBeInTheDocument()
    })

    it('shows the empty state when the load returns zero issues', async () => {
        await renderEmptyStateAfterLoad(issuesQuery())

        expect(screen.getByText('No issues found')).toBeInTheDocument()
        expect(screen.queryByText('Could not load issues')).not.toBeInTheDocument()
    })
})
