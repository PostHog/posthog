import { useActions, useValues } from 'kea'
import { useMemo } from 'react'

import { LemonSegmentedButton, LemonTable, LemonTag, Link, Tooltip } from '@posthog/lemon-ui'

import { LemonProgress } from 'lib/lemon-ui/LemonProgress'
import { LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { urls } from 'scenes/urls'

import { InsightVizNode, NodeKind, ProductKey } from '~/queries/schema/schema-general'
import { BaseMathType, ChartDisplayType, InsightLogicProps, PropertyFilterType, PropertyOperator } from '~/types'

import { visionQuotaLogic } from '../../logics/visionQuotaLogic'
import { creditsToUsd, formatCreditCount, formatCredits, formatCreditsRange } from '../../utils/credits'
import { exhaustionForecast, hasCreditLimit, projectQuota } from '../../utils/quotaProjection'
import { OBSERVATION_CREDITS_BY_MODEL, ReplayScanner, modelName } from '../types'
import { SpendChartInterval, visionUsageLogic } from '../visionUsageLogic'
import { VisionInsightChart } from './VisionInsightChart'

const RECORDING_OBSERVED_EVENT = '$recording_observed'

const SPEND_CHART_INTERVAL_OPTIONS: { value: SpendChartInterval; label: string }[] = [
    { value: 'day', label: 'Daily' },
    { value: 'week', label: 'Weekly' },
    { value: 'month', label: 'Monthly' },
]

const SPEND_CHART_DATE_FROM: Record<Exclude<SpendChartInterval, 'day'>, string> = {
    week: '-90d',
    month: '-365d',
}

// Counted per model and priced in the formula: events predating the `credits` property would sum to zero.
const SPEND_CHART_MODEL_PRICES = Object.entries(OBSERVATION_CREDITS_BY_MODEL)
const SPEND_CHART_SERIES = SPEND_CHART_MODEL_PRICES.map(([model]) => ({
    kind: NodeKind.EventsNode as const,
    event: RECORDING_OBSERVED_EVENT,
    math: BaseMathType.TotalCount,
    properties: [
        {
            type: PropertyFilterType.Event as const,
            key: 'model_used',
            operator: PropertyOperator.Exact as const,
            value: model,
        },
    ],
}))
const SPEND_CHART_FORMULA = `(${SPEND_CHART_MODEL_PRICES.map(
    ([, credits], index) => `${String.fromCharCode(65 + index)}*${credits}`
).join(' + ')}) / 100`

export function VisionUsageTab(): JSX.Element {
    const { usageScanners, usageScannersLoading, spendChartInterval } = useValues(visionUsageLogic)
    const { setSpendChartInterval } = useActions(visionUsageLogic)
    const { quota } = useValues(visionQuotaLogic)

    const projection = projectQuota(quota)
    const hasCap = hasCreditLimit(quota)
    const forecastDate = quota
        ? exhaustionForecast(quota.credits_used, quota.credit_limit, quota.period_start, quota.period_end)
        : null

    const spenders = usageScanners.filter((s: ReplayScanner) => s.credits_this_month > 0)
    const zeroSpendCount = usageScanners.length - spenders.length
    const totalCredits = spenders.reduce((sum: number, s: ReplayScanner) => sum + s.credits_this_month, 0)

    // Memoized so re-renders can't churn the query; `tags.productKey` is required or the runner aborts.
    const spendChartQuery = useMemo<InsightVizNode>(
        () => ({
            kind: NodeKind.InsightVizNode,
            source: {
                kind: NodeKind.TrendsQuery,
                series: SPEND_CHART_SERIES,
                trendsFilter: {
                    display: ChartDisplayType.ActionsLineGraph,
                    // The /100 charts dollars (1 credit = $0.01).
                    formulaNodes: [{ formula: SPEND_CHART_FORMULA, custom_name: 'Spend' }],
                    aggregationAxisPrefix: '$',
                },
                dateRange: {
                    date_from:
                        spendChartInterval === 'day'
                            ? (quota?.period_start ?? '-30d')
                            : SPEND_CHART_DATE_FROM[spendChartInterval],
                    date_to: null,
                },
                interval: spendChartInterval,
                tags: { productKey: ProductKey.REPLAY_VISION },
            },
        }),
        [quota?.period_start, spendChartInterval]
    )
    const spendChartInsightProps = useMemo<InsightLogicProps>(
        () => ({
            dashboardItemId: 'new-replay-vision-usage-spend-chart',
            dataNodeCollectionId: 'replay-vision-usage',
        }),
        []
    )

    const columns: LemonTableColumns<ReplayScanner> = [
        {
            title: 'Scanner',
            key: 'name',
            width: '25%',
            render: (_, scanner) => (
                <div className="flex items-center gap-2">
                    <Link to={urls.replayVision(scanner.id)} className="font-semibold text-primary">
                        {scanner.name || '(untitled)'}
                    </Link>
                    {!scanner.enabled && <LemonTag type="muted">Disabled</LemonTag>}
                </div>
            ),
        },
        {
            title: 'Observations',
            key: 'observations_this_month',
            tooltip: 'Succeeded observations this billing period.',
            render: (_, scanner) => (
                <span className="text-sm tabular-nums">{scanner.observations_this_month.toLocaleString()}</span>
            ),
        },
        {
            title: 'Price per observation',
            key: 'credits_per_observation',
            render: (_, scanner) => (
                <span className="text-sm whitespace-nowrap">
                    <span className="tabular-nums">
                        {scanner.credits_per_observation} credit{scanner.credits_per_observation === 1 ? '' : 's'}
                    </span>
                    <span className="text-muted"> · {modelName(scanner.model)}</span>
                </span>
            ),
        },
        {
            title: 'Sampling',
            key: 'sampling_rate',
            tooltip: 'The main cost lever: lower sampling scans fewer of the matching sessions.',
            render: (_, scanner) => (
                <span className="text-sm tabular-nums">
                    {(scanner.sampling_rate * 100).toFixed(scanner.sampling_rate < 0.1 ? 2 : 1)}%
                </span>
            ),
        },
        {
            title: 'Share of spend',
            key: 'credits_this_month',
            width: '30%',
            render: (_, scanner) => {
                const sharePct = totalCredits > 0 ? Math.round((scanner.credits_this_month / totalCredits) * 100) : 0
                return (
                    <div className="flex flex-col gap-1">
                        <span className="text-sm tabular-nums flex items-baseline justify-between gap-2">
                            {formatCredits(scanner.credits_this_month)}
                            <span className="text-muted">{sharePct}%</span>
                        </span>
                        <LemonProgress percent={sharePct} />
                    </div>
                )
            },
        },
    ]

    return (
        <div className="flex flex-col gap-4">
            <div className="bg-bg-light rounded p-4 flex flex-col InsightCard h-80">
                <div className="flex items-center justify-between gap-2 mb-1">
                    <h3 className="text-base font-semibold m-0">Spend over time</h3>
                    <div className="flex items-center gap-3">
                        {quota && (
                            <Tooltip
                                title={`≈ ${creditsToUsd(quota.credits_used)}${
                                    hasCap ? ` of ${creditsToUsd(quota.credit_limit ?? 0)}` : ''
                                }`}
                            >
                                <span className="text-xs text-muted tabular-nums">
                                    {hasCap
                                        ? formatCreditsRange(quota.credits_used, quota.credit_limit ?? 0)
                                        : formatCreditCount(quota.credits_used)}{' '}
                                    this period
                                    {projection.resetsOn ? `, resets ${projection.resetsOn}` : ''}
                                </span>
                            </Tooltip>
                        )}
                        <LemonSegmentedButton
                            size="small"
                            value={spendChartInterval}
                            onChange={(value) => setSpendChartInterval(value)}
                            options={SPEND_CHART_INTERVAL_OPTIONS}
                        />
                    </div>
                </div>
                <p className="text-muted text-xs mb-3">Across all scanners</p>
                <VisionInsightChart
                    query={spendChartQuery}
                    insightProps={spendChartInsightProps}
                    className="flex-1 flex flex-col min-h-0"
                />
            </div>
            {forecastDate && (
                <div className="text-xs text-warning">
                    At the current pace, you'll reach your spend limit around {forecastDate}. Scanning pauses at the
                    limit until the period resets.
                </div>
            )}
            <LemonTable
                columns={columns}
                dataSource={spenders}
                loading={usageScannersLoading}
                rowKey={(scanner) => scanner.id}
                emptyState="No spend this period yet. Costs appear here once scanners produce observations."
                footer={
                    zeroSpendCount > 0 ? (
                        <div className="px-3 py-2 text-xs text-muted">
                            {zeroSpendCount} scanner{zeroSpendCount === 1 ? '' : 's'} with no spend this period
                        </div>
                    ) : undefined
                }
            />
        </div>
    )
}
