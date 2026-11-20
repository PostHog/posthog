import { useValues } from 'kea'
import { ReactNode } from 'react'

import { DataNodeLogicProps, dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import { TrendsQuery } from '~/queries/schema/schema-general'

import type { SignalReportCheckApi } from 'products/signals/frontend/generated/api.schemas'

import { SignalReport } from '../../types'
import { asReportMetricSeriesQuery, reportMetricSeriesPoints } from '../../utils/reportMetrics'
import { ReportMeasureStage } from './stages/ReportMeasureStage'

interface MeasureProps {
    report: SignalReport
    checks: SignalReportCheckApi[]
    children?: ReactNode
}

function MeasureWithSeries({
    query,
    metricId,
    ...props
}: MeasureProps & { query: TrendsQuery; metricId: string }): JSX.Element {
    // The same key as the observation card, so the two share one query.
    const seriesProps: DataNodeLogicProps = {
        key: `ReportMetricSeries.${props.report.id}.${metricId}`,
        query,
        dataNodeCollectionId: `report-metrics-${props.report.id}`,
        autoLoad: true,
    }
    const { response } = useValues(dataNodeLogic(seriesProps))
    return <ReportMeasureStage {...props} metricPoints={response ? reportMetricSeriesPoints(response) : null} />
}

/** The Measure stage with the primary metric loaded. A report with no metric query shows the checks only. */
export function QuillReportMeasureStage(props: MeasureProps): JSX.Element {
    const primaryMetric = props.report.metrics?.find((metric) => metric.role === 'primary') ?? null
    const seriesQuery = primaryMetric ? asReportMetricSeriesQuery(primaryMetric) : null

    if (!primaryMetric || !seriesQuery) {
        return <ReportMeasureStage {...props} metricPoints={null} />
    }
    return <MeasureWithSeries {...props} query={seriesQuery.source} metricId={primaryMetric.metric_id} />
}
