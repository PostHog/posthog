import { useActions, useValues } from 'kea'
import { useMemo } from 'react'

import { LemonSegmentedButton, LemonSwitch, LemonTable, Link, Spinner, Tooltip } from '@posthog/lemon-ui'

import { FEATURE_FLAGS } from 'lib/constants'
import { LemonProgress } from 'lib/lemon-ui/LemonProgress'
import { LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { urls } from 'scenes/urls'

import { InsightVizNode, NodeKind, ProductKey } from '~/queries/schema/schema-general'
import { BaseMathType, ChartDisplayType, InsightLogicProps, PropertyFilterType, PropertyOperator } from '~/types'

import { VisionDocsLink } from '../../components/DocsLink'
import { CreditPriceNote } from '../../components/PricingLink'
import { visionQuotaLogic } from '../../logics/visionQuotaLogic'
import { getReplayVisionEditDisabledReason } from '../../utils/accessControl'
import { creditsToUsd, formatCreditCount, formatCreditsMaybeUsd, formatCreditsRange } from '../../utils/credits'
import { exhaustionForecast, hasCreditLimit, projectQuota } from '../../utils/quotaProjection'
import { STARTUP_CAP_EXPLANATION } from '../../utils/startupCap'
import { OBSERVATION_CREDITS_BY_MODEL, ReplayScanner, modelName, modelNamingVariant } from '../types'
import { SpendChartInterval, visionUsageLogic } from '../visionUsageLogic'
import { QuotaMeterBar } from './QuotaMeterBar'
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
const SPEND_CHART_CREDITS_FORMULA = SPEND_CHART_MODEL_PRICES.map(
    ([, credits], index) => `${String.fromCharCode(65 + index)}*${credits}`
).join(' + ')

export function VisionUsageTab(): JSX.Element {
    const { usageScanners, usageScannersLoading, spendChartInterval, togglingScannerIds } = useValues(visionUsageLogic)
    const { setSpendChartInterval, toggleScannerEnabled } = useActions(visionUsageLogic)
    const {
        displayQuota: quota,
        quotaLoading,
        showUsd,
        billedCredits,
        billedLimitCredits,
        showStartupCap,
    } = useValues(visionQuotaLogic)
    const { featureFlags } = useValues(featureFlagLogic)
    const namingVariant = modelNamingVariant(featureFlags[FEATURE_FLAGS.REPLAY_VISION_MODEL_TIER_NAMING_EXPERIMENT])

    const projection = projectQuota(quota)
    const hasCap = hasCreditLimit(quota)
    const forecastDate = quota
        ? exhaustionForecast(quota.credits_used, quota.credit_limit, quota.period_start, quota.period_end)
        : null

    const spendTooltip =
        quota && showUsd
            ? `≈ ${creditsToUsd(billedCredits)} billed${hasCap ? ` of ${creditsToUsd(billedLimitCredits)}` : ''}.${
                  showStartupCap ? ` ${STARTUP_CAP_EXPLANATION}` : ''
              }`
            : undefined

    const rows = usageScanners.filter(
        (s: ReplayScanner) => s.credits_this_month > 0 || (s.enabled && (s.estimated_monthly_credits ?? 0) > 0)
    )
    const hiddenCount = usageScanners.length - rows.length
    const totalCredits = rows.reduce((sum: number, s: ReplayScanner) => sum + s.credits_this_month, 0)
    // A $0 limit really blocks scanning, but as a bar denominator it deliberately counts as "no limit".
    const creditLimit = hasCap && quota.credit_limit > 0 ? quota.credit_limit : null

    // The period window comes from the quota, so dispatching before it lands would abort the in-flight query
    // and refetch. A failed load still resolves (the loader keeps the last snapshot) so this can't hang.
    const quotaResolved = quota !== null || !quotaLoading

    // Memoized so re-renders can't churn the query; `tags.productKey` is required or the runner aborts.
    const spendChartQuery = useMemo<InsightVizNode>(
        () => ({
            kind: NodeKind.InsightVizNode,
            source: {
                kind: NodeKind.TrendsQuery,
                series: SPEND_CHART_SERIES,
                trendsFilter: {
                    display: ChartDisplayType.ActionsLineGraph,
                    // Credits, not dollars: the free tier applies cumulatively per period, so no per-bucket
                    // conversion can chart billed dollars; those live in the tooltip beside the chart.
                    formulaNodes: [{ formula: SPEND_CHART_CREDITS_FORMULA, custom_name: 'Credits' }],
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
                <Link to={urls.replayVision(scanner.id)} className="font-semibold text-primary">
                    {scanner.name || '(untitled)'}
                </Link>
            ),
        },
        {
            title: 'Enabled',
            key: 'enabled',
            tooltip: 'Enabled scanners run automatically on a schedule. Disabled scanners run on-demand only.',
            render: (_, scanner) => (
                <LemonSwitch
                    checked={scanner.enabled}
                    onChange={() => toggleScannerEnabled(scanner)}
                    loading={togglingScannerIds.includes(scanner.id)}
                    disabledReason={getReplayVisionEditDisabledReason(scanner.user_access_level)}
                    data-attr="vision-usage-scanner-toggle-enabled"
                    data-ph-capture-attribute-scanner-type={scanner.scanner_type}
                    data-ph-capture-attribute-will-be-enabled={!scanner.enabled}
                />
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
                    <span className="text-muted"> · {modelName(scanner.model, namingVariant)}</span>
                </span>
            ),
        },
        {
            title: 'Sampling',
            key: 'sampling_rate',
            tooltip: "Lower sampling scans fewer of the matching sessions. It's the main cost lever.",
            render: (_, scanner) => (
                <span className="text-sm tabular-nums">
                    {(scanner.sampling_rate * 100).toFixed(scanner.sampling_rate < 0.1 ? 2 : 1)}%
                </span>
            ),
        },
        {
            title: 'Estimated monthly spend',
            key: 'estimated_monthly_credits',
            width: '20%',
            tooltip:
                "Based on the scanner's filters and sampling. The bar shows how much of the spend limit it would take up. Updates when the scanner is saved.",
            render: (_, scanner) => {
                // The fleet projection skips disabled scanners, so an estimate here wouldn't add up to the meter.
                if (!scanner.enabled || scanner.estimated_monthly_credits === null) {
                    return <span className="text-muted">—</span>
                }
                const estimatedCredits = scanner.estimated_monthly_credits
                if (creditLimit === null) {
                    return (
                        <span className="text-sm tabular-nums">
                            ~{formatCreditsMaybeUsd(estimatedCredits, showUsd)}
                        </span>
                    )
                }
                const limitPct = (estimatedCredits / creditLimit) * 100
                const limitPctLabel = limitPct > 0 && limitPct < 1 ? '< 1' : String(Math.round(limitPct))
                return (
                    <div className="flex flex-col gap-1">
                        <span className="text-sm tabular-nums flex items-baseline justify-between gap-2">
                            ~{formatCreditsMaybeUsd(estimatedCredits, showUsd)}
                            <span className="text-muted">{limitPctLabel}% of spend limit</span>
                        </span>
                        <QuotaMeterBar
                            size="small"
                            usedPct={0}
                            projected={limitPct > 0 ? [{ pct: limitPct, barClass: 'bg-accent', striped: true }] : []}
                            valueNow={limitPct}
                            label={`Estimated ${limitPctLabel}% of the monthly spend limit`}
                        />
                    </div>
                )
            },
        },
        {
            title: 'Spend this period',
            key: 'credits_this_month',
            width: '30%',
            className: 'pl-6',
            tooltip: 'How much of the total spend this billing period came from this scanner.',
            render: (_, scanner) => {
                const sharePct = totalCredits > 0 ? Math.round((scanner.credits_this_month / totalCredits) * 100) : 0
                return (
                    <div className="flex flex-col gap-1">
                        <span className="text-sm tabular-nums flex items-baseline justify-between gap-2">
                            {formatCreditsMaybeUsd(scanner.credits_this_month, showUsd)}
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
            <div className="bg-bg-light rounded p-4 flex flex-col InsightCard min-h-80 lg:h-80">
                <div className="flex flex-wrap items-center justify-between gap-2 mb-1">
                    <h3 className="text-base font-semibold m-0">Spend over time</h3>
                    <div className="flex flex-wrap items-center gap-3">
                        {quota && (
                            <Tooltip title={spendTooltip}>
                                <span className="text-xs text-muted tabular-nums">
                                    {hasCap
                                        ? formatCreditsRange(quota.credits_used, quota.credit_limit ?? 0)
                                        : formatCreditCount(quota.credits_used)}{' '}
                                    this billing period
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
                {quotaResolved ? (
                    <VisionInsightChart
                        query={spendChartQuery}
                        insightProps={spendChartInsightProps}
                        className="flex-1 flex flex-col min-h-0"
                    />
                ) : (
                    <div className="flex-1 flex items-center justify-center">
                        <Spinner />
                    </div>
                )}
            </div>
            {forecastDate && (
                <div className="text-xs text-warning">
                    At the current pace, you'll reach your spend limit around {forecastDate}. Scanning pauses at the
                    limit until the period resets.
                </div>
            )}
            <LemonTable
                columns={columns}
                dataSource={rows}
                loading={usageScannersLoading}
                rowKey={(scanner) => scanner.id}
                emptyState={
                    <>
                        No spend this billing period yet. Costs appear here once scanners produce observations.{' '}
                        <VisionDocsLink page="quota-and-limits" dataAttr="vision-empty-docs-link-usage">
                            Learn how credits and limits work
                        </VisionDocsLink>
                    </>
                }
                footer={
                    hiddenCount > 0 ? (
                        <div className="px-3 py-2 text-xs text-muted">
                            {hiddenCount} scanner{hiddenCount === 1 ? '' : 's'} with no spend or estimate this billing
                            period
                        </div>
                    ) : undefined
                }
            />
            <div className="text-xs text-muted">
                <CreditPriceNote dataAttr="vision-pricing-link-usage" />
            </div>
        </div>
    )
}
