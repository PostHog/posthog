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
    cn,
} from '@posthog/quill'

import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import { EndpointsUsageOverviewItemKey, EndpointsUsageOverviewQueryResponse } from '~/queries/schema/schema-general'

import { endpointsUsageLogic } from './endpointsUsageLogic'
import { QuillEndpointsUsageOverview } from './nodes/QuillEndpointsUsageOverview'
import { QuillEndpointsUsageChartCard } from './QuillEndpointsUsageChartCard'
import { QuillEndpointsUsageSection } from './QuillEndpointsUsageSection'
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

    const tiles = (metricKeys: EndpointsUsageOverviewItemKey[]): JSX.Element => (
        <QuillEndpointsUsageOverview
            results={overview?.results}
            loading={loading}
            metricKeys={metricKeys}
            // A row above the charts when narrow, a column beside them when wide, stretched to the charts' height.
            className={cn(
                'h-full auto-rows-fr @min-[60rem]/main-content:grid-cols-1',
                metricKeys.length === 3 ? 'grid-cols-3' : 'grid-cols-2'
            )}
        />
    )

    return (
        <>
            <QuillEndpointsUsageSection
                title="Executions"
                description="How often your endpoints ran, and how many of those runs read a materialized table."
                tiles={tiles(['total_requests', 'materialized_requests', 'inline_requests'])}
            >
                <QuillEndpointsUsageChartCard
                    title="Executions over time"
                    query={requestsTrendsQuery}
                    refreshKey={refreshKey}
                />
            </QuillEndpointsUsageSection>
            <QuillEndpointsUsageSection
                title="Performance"
                description="How many executions failed, and how long the rest took to answer."
                tiles={tiles(['error_rate', 'avg_query_duration_ms', 'p95_query_duration_ms'])}
            >
                <QuillEndpointsUsageChartCard
                    title="Error rate over time"
                    query={errorRateTrendsQuery}
                    refreshKey={refreshKey}
                />
                <QuillEndpointsUsageChartCard
                    title="Average duration over time"
                    query={queryDurationTrendsQuery}
                    refreshKey={refreshKey}
                />
            </QuillEndpointsUsageSection>
            <QuillEndpointsUsageSection
                title="Cost"
                description="The data scanned and the processing time the executions used."
                tiles={tiles(['total_bytes_read', 'total_cpu_seconds'])}
            >
                <QuillEndpointsUsageChartCard
                    title="Bytes read over time"
                    query={bytesReadTrendsQuery}
                    refreshKey={refreshKey}
                />
                <QuillEndpointsUsageChartCard
                    title="CPU time over time"
                    query={cpuSecondsTrendsQuery}
                    refreshKey={refreshKey}
                />
            </QuillEndpointsUsageSection>
            <QuillEndpointsUsageTable />
        </>
    )
}
