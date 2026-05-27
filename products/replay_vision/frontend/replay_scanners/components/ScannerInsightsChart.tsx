import { Query } from '~/queries/Query/Query'
import { EventPropertyFilter, InsightVizNode, NodeKind, ProductKey, TrendsQuery } from '~/queries/schema/schema-general'
import { BaseMathType, ChartDisplayType, PropertyFilterType, PropertyMathType, PropertyOperator } from '~/types'

import { ScannerType } from '../types'

const RECORDING_OBSERVED_EVENT = '$recording_observed'
const DEFAULT_DATE_FROM = '-14d'
const COLLECTION_ID = 'replay-vision-scanner-insights'

function scannerIdFilter(scannerId: string): EventPropertyFilter {
    return {
        type: PropertyFilterType.Event,
        key: 'scanner_id',
        operator: PropertyOperator.Exact,
        value: scannerId,
    }
}

function buildQuery(scannerId: string, scannerType: ScannerType): TrendsQuery {
    const base = scannerIdFilter(scannerId)
    if (scannerType === 'monitor') {
        return {
            kind: NodeKind.TrendsQuery,
            series: [
                {
                    kind: NodeKind.EventsNode,
                    event: RECORDING_OBSERVED_EVENT,
                    math: BaseMathType.TotalCount,
                    name: 'Yes verdicts',
                    properties: [
                        base,
                        {
                            type: PropertyFilterType.Event,
                            key: 'scanner_output_verdict',
                            operator: PropertyOperator.Exact,
                            value: 'true',
                        },
                    ],
                },
                {
                    kind: NodeKind.EventsNode,
                    event: RECORDING_OBSERVED_EVENT,
                    math: BaseMathType.TotalCount,
                    name: 'Total observations',
                    properties: [base],
                },
            ],
            trendsFilter: { display: ChartDisplayType.ActionsLineGraph, formula: 'A / B * 100' },
            dateRange: { date_from: DEFAULT_DATE_FROM },
            interval: 'day',
        }
    }
    if (scannerType === 'classifier') {
        return {
            kind: NodeKind.TrendsQuery,
            series: [
                {
                    kind: NodeKind.EventsNode,
                    event: RECORDING_OBSERVED_EVENT,
                    math: BaseMathType.TotalCount,
                    name: 'Observations',
                    properties: [base],
                },
            ],
            breakdownFilter: {
                // Union fixed (`scanner_output_tags`) and freeform (`scanner_output_tags_freeform`); arrayJoin gives each tag its own series.
                breakdown:
                    "arrayJoin(arrayConcat(JSONExtract(ifNull(properties.scanner_output_tags, '[]'), 'Array(String)'), JSONExtract(ifNull(properties.scanner_output_tags_freeform, '[]'), 'Array(String)')))",
                breakdown_type: 'hogql',
            },
            trendsFilter: { display: ChartDisplayType.ActionsAreaGraph },
            dateRange: { date_from: DEFAULT_DATE_FROM },
            interval: 'day',
        }
    }
    if (scannerType === 'scorer') {
        const scoreSeries = (math: PropertyMathType, name: string): TrendsQuery['series'][number] => ({
            kind: NodeKind.EventsNode,
            event: RECORDING_OBSERVED_EVENT,
            math,
            math_property: 'scanner_output_score',
            name,
            properties: [base],
        })
        return {
            kind: NodeKind.TrendsQuery,
            series: [
                scoreSeries(PropertyMathType.Median, 'p50'),
                scoreSeries(PropertyMathType.P90, 'p90'),
                scoreSeries(PropertyMathType.Average, 'avg'),
            ],
            trendsFilter: { display: ChartDisplayType.ActionsLineGraph },
            dateRange: { date_from: DEFAULT_DATE_FROM },
            interval: 'day',
        }
    }
    return {
        kind: NodeKind.TrendsQuery,
        series: [
            {
                kind: NodeKind.EventsNode,
                event: RECORDING_OBSERVED_EVENT,
                math: BaseMathType.TotalCount,
                name: 'Observations',
                properties: [base],
            },
        ],
        trendsFilter: { display: ChartDisplayType.ActionsLineGraph },
        dateRange: { date_from: DEFAULT_DATE_FROM },
        interval: 'day',
    }
}

function chartTitle(scannerType: ScannerType): string {
    if (scannerType === 'monitor') {
        return 'Yes rate (%) over time'
    }
    if (scannerType === 'classifier') {
        return 'Tag mix over time'
    }
    if (scannerType === 'scorer') {
        return 'Score percentiles over time'
    }
    return 'Observations over time'
}

export function ScannerInsightsChart({
    scannerId,
    scannerType,
}: {
    scannerId: string
    scannerType: ScannerType
}): JSX.Element {
    // `tags.productKey` is required for ClickHouse query tagging; without it the runner aborts.
    const source: TrendsQuery = {
        ...buildQuery(scannerId, scannerType),
        tags: { productKey: ProductKey.REPLAY_VISION },
    }
    return (
        <div className="border rounded p-4 bg-surface-primary space-y-3">
            <div className="flex items-baseline justify-between gap-2">
                <span className="text-sm font-medium">{chartTitle(scannerType)}</span>
                <span className="text-xs text-muted">Last 14 days</span>
            </div>
            <div className="InsightCard h-80">
                <Query
                    query={{ kind: NodeKind.InsightVizNode, source } as InsightVizNode}
                    readOnly
                    embedded
                    inSharedMode
                    context={{
                        insightProps: {
                            dashboardItemId: `replay-vision-scanner-${scannerId}-chart`,
                            dataNodeCollectionId: COLLECTION_ID,
                        },
                    }}
                />
            </div>
        </div>
    )
}
