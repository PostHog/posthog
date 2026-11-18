import { useValues } from 'kea'

import { DataNodeLogicProps, dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import { TrendsQuery } from '~/queries/schema/schema-general'

import type { ReportMetricApi } from 'products/signals/frontend/generated/api.schemas'

import { reportMetricAggregate } from '../../utils/reportMetrics'
import { ReportSupportingMetric } from './ReportSupportingMetric'

export function ReportSupportingMetricQuery({
    reportId,
    metric,
    query,
}: {
    reportId: string
    metric: ReportMetricApi
    query: TrendsQuery
}): JSX.Element {
    const dataNodeProps: DataNodeLogicProps = {
        key: `ReportMetric.${reportId}.${metric.metric_id}`,
        query,
        dataNodeCollectionId: `report-metrics-${reportId}`,
        autoLoad: true,
    }
    const { response, responseError, responseLoading } = useValues(dataNodeLogic(dataNodeProps))

    return (
        <ReportSupportingMetric
            metric={metric}
            liveState={{
                value: reportMetricAggregate(response),
                loading: responseLoading,
                error: !!responseError,
            }}
        />
    )
}
