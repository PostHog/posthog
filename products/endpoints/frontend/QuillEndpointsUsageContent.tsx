import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconEndpoints } from '@posthog/icons'
import {
    Button,
    Empty,
    EmptyContent,
    EmptyDescription,
    EmptyHeader,
    EmptyTitle,
    IconStack,
    IconStackItem,
} from '@posthog/quill'

import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import { EndpointsUsageOverviewQueryResponse } from '~/queries/schema/schema-general'

import { endpointsUsageLogic } from './endpointsUsageLogic'
import { QuillEndpointsUsageOverview } from './nodes/QuillEndpointsUsageOverview'
import { QuillEndpointsUsageChartCard } from './QuillEndpointsUsageChartCard'
import { QuillEndpointsUsageTable } from './QuillEndpointsUsageTable'

let uniqueNode = 0

/** One run of the page's queries. A refresh remounts it, which runs every query again. */
export function QuillEndpointsUsageContent(): JSX.Element {
    const {
        overviewQuery,
        requestsTrendsQuery,
        errorRateTrendsQuery,
        queryDurationTrendsQuery,
        cpuSecondsTrendsQuery,
        bytesReadTrendsQuery,
        refreshKey,
        endpointFilter,
        materializationType,
    } = useValues(endpointsUsageLogic)
    const { setEndpointFilter, setMaterializationType } = useActions(endpointsUsageLogic)
    const [key] = useState(() => `EndpointsUsageOverview.page.${uniqueNode++}`)
    const logic = dataNodeLogic({ query: overviewQuery, key, dataNodeCollectionId: key })
    const { response, responseLoading, responseError } = useValues(logic)
    const { loadData } = useActions(logic)
    const overview = response as EndpointsUsageOverviewQueryResponse | undefined

    // A query that has not started reads as no response and not loading, so only a response counts as an answer.
    const loading = responseLoading || !overview
    const totalExecutions = overview?.results?.find((item) => item.key === 'total_requests')?.value ?? 0
    const filtersActive = endpointFilter.length > 0 || materializationType !== null

    if (responseError && !overview) {
        return (
            <Empty>
                <EmptyHeader>
                    <EmptyTitle>Couldn't load usage</EmptyTitle>
                    <EmptyDescription>{responseError}</EmptyDescription>
                </EmptyHeader>
                <EmptyContent>
                    <Button variant="outline" onClick={() => loadData()} data-attr="endpoints-usage-retry">
                        Try again
                    </Button>
                </EmptyContent>
            </Empty>
        )
    }

    // One verdict for the whole period beats eight empty tiles and five empty charts. It waits for the answer.
    if (!loading && totalExecutions === 0) {
        return (
            <Empty>
                <EmptyHeader>
                    <IconStack>
                        <IconStackItem color="var(--color-product-endpoints-light)">
                            <IconEndpoints />
                        </IconStackItem>
                    </IconStack>
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
        <>
            <QuillEndpointsUsageOverview results={overview?.results} loading={loading} />
            <div className="grid grid-cols-1 gap-4 @min-[60rem]/main-content:grid-cols-3">
                <QuillEndpointsUsageChartCard
                    title="Executions"
                    description="How many times your endpoints ran."
                    query={requestsTrendsQuery}
                    refreshKey={refreshKey}
                />
                <QuillEndpointsUsageChartCard
                    title="Error rate"
                    description="The share of executions that failed."
                    query={errorRateTrendsQuery}
                    refreshKey={refreshKey}
                />
                <QuillEndpointsUsageChartCard
                    title="Query duration"
                    description="The average time an execution took."
                    query={queryDurationTrendsQuery}
                    refreshKey={refreshKey}
                />
            </div>
            <div className="grid grid-cols-1 gap-4 @min-[48rem]/main-content:grid-cols-2">
                <QuillEndpointsUsageChartCard
                    title="CPU time"
                    description="The processing time your executions used."
                    query={cpuSecondsTrendsQuery}
                    refreshKey={refreshKey}
                />
                <QuillEndpointsUsageChartCard
                    title="Bytes read"
                    description="The data your executions scanned."
                    query={bytesReadTrendsQuery}
                    refreshKey={refreshKey}
                />
            </div>
            <QuillEndpointsUsageTable />
        </>
    )
}
