import { useActions, useValues } from 'kea'

import { IconGraph } from '@posthog/icons'
import { Button, Empty, EmptyContent, EmptyDescription, EmptyHeader, EmptyMedia, EmptyTitle } from '@posthog/quill'

import { EndpointsUsageOverviewQueryResponse } from '~/queries/schema/schema-general'

import { endpointsUsageLogic } from './endpointsUsageLogic'
import { QuillEndpointsUsageBreakdownTable } from './nodes/QuillEndpointsUsageBreakdownTable'
import { QuillEndpointsUsageOverview } from './nodes/QuillEndpointsUsageOverview'
import { QuillEndpointsUsageTrendsCard } from './nodes/QuillEndpointsUsageTrendsCard'
import { useEndpointsUsageQuery } from './nodes/useEndpointsUsageQuery'
import { QuillEndpointsUsageFilters } from './QuillEndpointsUsageFilters'

/** One run of the page's queries. A refresh remounts it, which runs every query again. */
function QuillEndpointsUsageContent(): JSX.Element {
    const {
        overviewQuery,
        requestsTrendsQuery,
        errorRateTrendsQuery,
        queryDurationTrendsQuery,
        cpuSecondsTrendsQuery,
        bytesReadTrendsQuery,
        endpointTableQuery,
        activeEndpointNames,
        endpointFilter,
        materializationType,
    } = useValues(endpointsUsageLogic)
    const { setEndpointFilter, setMaterializationType } = useActions(endpointsUsageLogic)
    const { response, responseLoading, responseError, retry } =
        useEndpointsUsageQuery<EndpointsUsageOverviewQueryResponse>(overviewQuery)

    // A query that has not started reads as no response and not loading, so only a response counts as an answer.
    const resolved = response !== undefined
    const loading = responseLoading || !resolved
    const totalExecutions = response?.results?.find((item) => item.key === 'total_requests')?.value ?? 0
    const filtersActive = endpointFilter.length > 0 || materializationType !== null

    if (responseError) {
        return (
            <Empty>
                <EmptyHeader>
                    <EmptyTitle>Could not load usage</EmptyTitle>
                    <EmptyDescription>Try again, or contact support if this continues.</EmptyDescription>
                </EmptyHeader>
                <EmptyContent>
                    <Button variant="outline" onClick={retry}>
                        Try again
                    </Button>
                </EmptyContent>
            </Empty>
        )
    }

    // One verdict for the whole page beats a wall of empty tiles and charts. It waits for the answer.
    if (!loading && totalExecutions === 0) {
        return (
            <Empty>
                <EmptyHeader>
                    <EmptyMedia variant="icon">
                        <IconGraph />
                    </EmptyMedia>
                    <EmptyTitle>No executions in this period</EmptyTitle>
                    <EmptyDescription>
                        {filtersActive
                            ? 'Choose a longer date range or clear the filters to see usage.'
                            : 'Choose a longer date range to see usage.'}
                    </EmptyDescription>
                </EmptyHeader>
                {filtersActive && (
                    <EmptyContent>
                        <Button
                            variant="outline"
                            onClick={() => {
                                setEndpointFilter([])
                                setMaterializationType(null)
                            }}
                            data-attr="endpoints-usage-clear-filters"
                        >
                            Clear filters
                        </Button>
                    </EmptyContent>
                )}
            </Empty>
        )
    }

    return (
        <div className="flex flex-col gap-4">
            <QuillEndpointsUsageOverview results={response?.results} loading={loading} />
            <QuillEndpointsUsageTrendsCard title="Executions over time" query={requestsTrendsQuery} />
            <div className="grid grid-cols-1 gap-4 @min-[48rem]/main-content:grid-cols-2">
                <QuillEndpointsUsageTrendsCard title="Error rate over time" query={errorRateTrendsQuery} />
                <QuillEndpointsUsageTrendsCard title="Query duration over time" query={queryDurationTrendsQuery} />
                <QuillEndpointsUsageTrendsCard title="CPU time over time" query={cpuSecondsTrendsQuery} />
                <QuillEndpointsUsageTrendsCard title="Bytes read over time" query={bytesReadTrendsQuery} />
            </div>
            <QuillEndpointsUsageBreakdownTable query={endpointTableQuery} activeEndpointNames={activeEndpointNames} />
        </div>
    )
}

export function QuillEndpointsUsage(): JSX.Element {
    const { refreshKey } = useValues(endpointsUsageLogic)

    return (
        <div className="flex flex-col gap-4" data-quill data-attr="endpoints-usage">
            <QuillEndpointsUsageFilters />
            <QuillEndpointsUsageContent key={refreshKey} />
        </div>
    )
}
