import { useValues } from 'kea'
import { useMemo } from 'react'

import { Link } from 'lib/lemon-ui/Link'
import { humanFriendlyDuration, humanFriendlyNumber, humanizeBytes } from 'lib/utils'
import { urls } from 'scenes/urls'

import { Query } from '~/queries/Query/Query'
import { DataTableNode, NodeKind } from '~/queries/schema/schema-general'
import { QueryContext } from '~/queries/types'

import { EndpointsUsageFilters } from './EndpointsUsageFilters'
import { endpointsUsageLogic } from './endpointsUsageLogic'

export function EndpointsUsage({ tabId }: { tabId: string }): JSX.Element {
    const {
        overviewQuery,
        requestsTrendsQuery,
        bytesReadTrendsQuery,
        cpuSecondsTrendsQuery,
        queryDurationTrendsQuery,
        errorRateTrendsQuery,
        endpointTableQuery,
    } = useValues(endpointsUsageLogic({ tabId }))

    const tableContext: QueryContext<DataTableNode> = useMemo(
        () => ({
            columns: {
                endpoint: {
                    title: 'Endpoint',
                    render: ({ value }) => {
                        if (!value || typeof value !== 'string') {
                            return <>{value}</>
                        }
                        return <Link to={urls.endpoint(value)}>{value}</Link>
                    },
                },
                requests: {
                    title: 'Executions',
                    render: ({ value }) => <>{humanFriendlyNumber(value as number)}</>,
                },
                bytes_read: {
                    title: 'Bytes read',
                    render: ({ value }) => <>{humanizeBytes(value as number)}</>,
                },
                cpu_seconds: {
                    title: 'CPU time',
                    render: ({ value }) => <>{humanFriendlyDuration(value as number)}</>,
                },
                avg_query_duration_ms: {
                    title: 'Avg query duration',
                    render: ({ value }) => <>{humanFriendlyDuration((value as number) / 1000)}</>,
                },
                error_rate: {
                    title: 'Error rate',
                    render: ({ value }) => <>{((value as number) * 100).toFixed(2)}%</>,
                },
            },
        }),
        []
    )

    return (
        <>
            <EndpointsUsageFilters tabId={tabId} />
            <div className="mt-4 grid grid-cols-1 md:grid-cols-4 gap-x-4 gap-y-8">
                <div className="col-span-1 md:col-span-4 flex flex-col">
                    <h2 className="mb-3">Overview</h2>
                    <Query query={overviewQuery} readOnly />
                </div>

                {/* Row 1: Executions, Error rate, Query duration */}
                <div className="col-span-1 md:col-span-4 grid grid-cols-1 md:grid-cols-3 gap-4">
                    <div className="flex flex-col">
                        <h2 className="mb-3">Executions over time</h2>
                        <Query query={requestsTrendsQuery} readOnly />
                    </div>
                    <div className="flex flex-col">
                        <h2 className="mb-3">Error rate over time</h2>
                        <Query query={errorRateTrendsQuery} readOnly />
                    </div>
                    <div className="flex flex-col">
                        <h2 className="mb-3">Query duration over time</h2>
                        <Query query={queryDurationTrendsQuery} readOnly />
                    </div>
                </div>

                {/* Row 2: CPU time, Bytes read */}
                <div className="col-span-1 md:col-span-2 flex flex-col">
                    <h2 className="mb-3">CPU time over time</h2>
                    <Query query={cpuSecondsTrendsQuery} readOnly />
                </div>

                <div className="col-span-1 md:col-span-2 flex flex-col">
                    <h2 className="mb-3">Bytes read over time</h2>
                    <Query query={bytesReadTrendsQuery} readOnly />
                </div>

                <div className="col-span-1 md:col-span-4 flex flex-col">
                    <h2 className="mb-3">Endpoints breakdown</h2>
                    <Query
                        query={
                            {
                                kind: NodeKind.DataTableNode,
                                source: endpointTableQuery,
                                full: true,
                                showActions: false,
                                embedded: false,
                            } as DataTableNode
                        }
                        context={tableContext}
                        readOnly
                    />
                </div>
            </div>
        </>
    )
}
