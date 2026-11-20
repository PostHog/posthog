import { useValues } from 'kea'

import { Query } from '~/queries/Query/Query'

import { endpointsUsageLogic } from './endpointsUsageLogic'
import { QuillEndpointsUsageChartCard } from './QuillEndpointsUsageChartCard'
import { QuillEndpointsUsageFilters } from './QuillEndpointsUsageFilters'
import { QuillEndpointsUsageTable } from './QuillEndpointsUsageTable'

export function QuillEndpointsUsage(): JSX.Element {
    const {
        overviewQuery,
        requestsTrendsQuery,
        errorRateTrendsQuery,
        queryDurationTrendsQuery,
        cpuSecondsTrendsQuery,
        bytesReadTrendsQuery,
        refreshKey,
    } = useValues(endpointsUsageLogic)

    return (
        <div className="flex flex-col gap-4" data-quill data-attr="endpoints-usage">
            <QuillEndpointsUsageFilters />
            <Query key={`overview-${refreshKey}`} query={overviewQuery} readOnly />
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
            <QuillEndpointsUsageTable key={`table-${refreshKey}`} />
        </div>
    )
}
