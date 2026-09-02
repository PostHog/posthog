import { useActions, useValues } from 'kea'

import { LemonSwitch, Link, Spinner, Tooltip } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'
import { LemonProgress } from 'lib/lemon-ui/LemonProgress'
import { LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { LemonTable } from 'lib/lemon-ui/LemonTable'
import { urls } from 'scenes/urls'

import { ProductKey } from '~/queries/schema/schema-general'

import { VisionDocsLink } from '../../components/DocsLink'
import { CreditPriceNote } from '../../components/PricingLink'
import { visionQuotaLogic } from '../../logics/visionQuotaLogic'
import { getReplayVisionEditDisabledReason } from '../../utils/accessControl'
import { creditsToUsd, formatCreditCount, formatCreditsMaybeUsd } from '../../utils/credits'
import { fleetContributions } from '../../utils/quotaContributions'
import { spendVerdict, verdictColorVar, verdictTextClass } from '../../utils/spendVerdict'
import { STARTUP_CAP_EXPLANATION } from '../../utils/startupCap'
import { ReplayScanner } from '../types'
import { visionUsageLogic } from '../visionUsageLogic'
import { SpendTrajectoryChart } from './SpendTrajectoryChart'

export function VisionUsageTab(): JSX.Element {
    const { usageScanners, usageScannersLoading, togglingScannerIds, spendSeries, spendSeriesLoading } =
        useValues(visionUsageLogic)
    const { toggleScannerEnabled } = useActions(visionUsageLogic)
    const {
        displayQuota: quota,
        quotaLoading,
        showUsd,
        billedCredits,
        billedLimitCredits,
        showStartupCap,
        onFreePlan,
    } = useValues(visionQuotaLogic)

    const verdict = spendVerdict(quota, fleetContributions(quota), { onFreePlan })
    const statusText = verdictTextClass(verdict.kind)
    const hasCap = verdict.hasCap
    const resetsOn = quota?.period_end ? dayjs(quota.period_end) : null
    const daysToReset = resetsOn ? Math.max(resetsOn.startOf('day').diff(dayjs().startOf('day'), 'day'), 0) : null

    // Demand is the unclamped run rate; actual spend pauses at the limit, so the tile shows the clamp.
    const projectedDemandCredits = verdict.projectedDemandCredits
    const projectedTotalCredits =
        projectedDemandCredits !== null && quota
            ? hasCap
                ? Math.min(projectedDemandCredits, quota.credit_limit ?? 0)
                : projectedDemandCredits
            : null
    const projectedPctOfLimit =
        quota && hasCap && (quota.credit_limit ?? 0) > 0 && projectedTotalCredits !== null
            ? Math.round((projectedTotalCredits / (quota.credit_limit ?? 1)) * 100)
            : null
    const capReachLabel =
        verdict.kind === 'danger' && verdict.projection.capReachDate
            ? verdict.projection.capReachDate.format('MMM D')
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
            align: 'right',
            tooltip: 'Succeeded observations this billing period.',
            render: (_, scanner) => (
                <div className="text-sm tabular-nums text-right whitespace-nowrap">
                    {scanner.observations_this_month.toLocaleString()}
                </div>
            ),
        },
        {
            title: 'Price',
            key: 'credits_per_observation',
            align: 'right',
            render: (_, scanner) => (
                <div className="text-sm text-secondary text-right whitespace-nowrap tabular-nums">
                    {formatCreditCount(scanner.credits_per_observation)}/observation
                </div>
            ),
        },
        {
            title: 'Spent this period',
            key: 'credits_this_month',
            align: 'right',
            render: (_, scanner) => (
                <div className="text-sm tabular-nums text-right whitespace-nowrap">
                    {formatCreditsMaybeUsd(scanner.credits_this_month, showUsd)}
                </div>
            ),
        },
        {
            title: 'Share of spend',
            key: 'share',
            width: '18%',
            render: (_, scanner) => {
                const sharePct = totalCredits > 0 ? Math.round((scanner.credits_this_month / totalCredits) * 100) : 0
                return (
                    <div className="flex items-center gap-2">
                        <LemonProgress percent={sharePct} className="flex-1" />
                        <span className="text-xs text-secondary tabular-nums w-8 text-right">{sharePct}%</span>
                    </div>
                )
            },
        },
        {
            title: 'Projected monthly',
            key: 'estimated_monthly_credits',
            align: 'right',
            tooltip: "Based on the scanner's filters and sampling. Updates when the scanner is saved.",
            render: (_, scanner) => {
                if (!scanner.enabled || scanner.estimated_monthly_credits === null) {
                    return <div className="text-secondary text-right">—</div>
                }
                return (
                    <div className="text-sm tabular-nums text-secondary text-right whitespace-nowrap">
                        ~{formatCreditCount(scanner.estimated_monthly_credits)}
                    </div>
                )
            },
        },
    ]

    return (
        <div className="flex flex-col gap-4">
            <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
                <div className="bg-bg-light border rounded p-4 flex flex-col gap-1" data-attr="vision-usage-tile-spent">
                    <span className="text-muted text-xs font-medium uppercase">Spent</span>
                    {quota ? (
                        <Tooltip title={spendTooltip}>
                            <span className="text-2xl font-semibold tabular-nums">
                                {Math.round(quota.credits_used).toLocaleString('en-US')}{' '}
                                <span className="text-sm font-normal text-secondary">credits</span>
                            </span>
                        </Tooltip>
                    ) : (
                        <span className="text-2xl font-semibold">{quotaLoading ? <Spinner /> : '—'}</span>
                    )}
                    {quota && showUsd && (
                        <span className="text-xs text-secondary tabular-nums">
                            ≈ {creditsToUsd(billedCredits)} billed
                        </span>
                    )}
                    <span className="text-xs text-secondary">
                        <CreditPriceNote dataAttr="vision-pricing-link-usage" />
                    </span>
                </div>
                <div
                    className="bg-bg-light border rounded p-4 flex flex-col gap-1"
                    data-attr="vision-usage-tile-projected"
                >
                    <span className="text-muted text-xs font-medium uppercase">
                        Projected by {resetsOn ? resetsOn.format('MMM D') : 'period end'}
                    </span>
                    {quota && projectedTotalCredits !== null ? (
                        <span className={`text-2xl font-semibold tabular-nums ${statusText}`}>
                            {projectedTotalCredits.toLocaleString('en-US')}{' '}
                            <span className="text-sm font-normal text-secondary">credits</span>
                        </span>
                    ) : (
                        <span className="text-2xl font-semibold">{quotaLoading ? <Spinner /> : '—'}</span>
                    )}
                    <span
                        className={`text-xs tabular-nums ${verdict.kind === 'paused' || capReachLabel ? 'text-danger' : 'text-secondary'}`}
                    >
                        {verdict.kind === 'paused'
                            ? 'limit reached, scanning is paused'
                            : capReachLabel
                              ? `hits the limit around ${capReachLabel}`
                              : projectedPctOfLimit !== null
                                ? `${projectedPctOfLimit}% of limit`
                                : 'no limit set'}
                    </span>
                    {(verdict.kind === 'paused' || capReachLabel !== null) && (
                        <span className="text-xs">
                            <Link to={urls.organizationBilling([ProductKey.REPLAY_VISION])}>
                                Increase your spending limit
                            </Link>{' '}
                            to keep scanning.
                        </span>
                    )}
                </div>
                <div className="bg-bg-light border rounded p-4 flex flex-col gap-1" data-attr="vision-usage-tile-limit">
                    <span className="text-muted text-xs font-medium uppercase">Monthly limit</span>
                    {quota ? (
                        <span className="text-2xl font-semibold tabular-nums">
                            {hasCap ? Math.round(quota.credit_limit ?? 0).toLocaleString('en-US') : 'None set'}
                            {hasCap && <span className="text-sm font-normal text-secondary"> credits</span>}
                        </span>
                    ) : (
                        <span className="text-2xl font-semibold">{quotaLoading ? <Spinner /> : '—'}</span>
                    )}
                    <span className="text-xs text-secondary tabular-nums">
                        {hasCap ? (
                            <>
                                {showUsd ? `≈ ${creditsToUsd(billedLimitCredits)} · ` : ''}
                                <Link to={urls.organizationBilling([ProductKey.REPLAY_VISION])}>change</Link>
                            </>
                        ) : (
                            <>
                                <Link to={urls.organizationBilling([ProductKey.REPLAY_VISION])}>
                                    Set a spending limit
                                </Link>{' '}
                                to control spend.
                            </>
                        )}
                    </span>
                </div>
                <div
                    className="bg-bg-light border rounded p-4 flex flex-col gap-1"
                    data-attr="vision-usage-tile-resets"
                >
                    <span className="text-muted text-xs font-medium uppercase">Resets in</span>
                    <span className="text-2xl font-semibold tabular-nums">
                        {daysToReset !== null ? `${daysToReset} ${daysToReset === 1 ? 'day' : 'days'}` : '—'}
                    </span>
                    <span className="text-xs text-secondary">{resetsOn ? resetsOn.format('MMMM D') : ''}</span>
                </div>
            </div>

            <div className="bg-bg-light border rounded p-4 flex flex-col gap-2">
                <div className="flex flex-wrap items-baseline justify-between gap-2">
                    <h3 className="text-base font-semibold m-0">Spend this period</h3>
                    {quota && (
                        <span className="text-xs text-secondary tabular-nums">
                            {hasCap
                                ? `${Math.round(quota.credits_used).toLocaleString('en-US')} of ${formatCreditCount(quota.credit_limit ?? 0)}`
                                : formatCreditCount(quota.credits_used)}
                            {resetsOn ? ` · resets ${resetsOn.format('MMMM D')}` : ''}
                        </span>
                    )}
                </div>
                {quota && spendSeries ? (
                    spendSeries.length > 0 || quota.credits_used > 0 ? (
                        <SpendTrajectoryChart
                            quota={quota}
                            dailyCredits={spendSeries}
                            projectedTotal={projectedDemandCredits ?? quota.credits_used}
                            capReachDate={verdict.projection.capReachDate}
                            statusVar={verdictColorVar(verdict.kind)}
                        />
                    ) : (
                        <div className="flex items-center justify-center h-40 text-sm text-secondary">
                            Costs appear here once scanners produce observations.{' '}
                            <VisionDocsLink page="quota-and-limits" dataAttr="vision-empty-docs-link-usage">
                                Learn how credits and limits work
                            </VisionDocsLink>
                        </div>
                    )
                ) : (
                    <div className="flex items-center justify-center h-40">
                        {quotaLoading || spendSeriesLoading ? (
                            <Spinner />
                        ) : (
                            <span className="text-sm text-secondary">
                                Couldn't load spend data. Refresh to try again.
                            </span>
                        )}
                    </div>
                )}
            </div>

            <LemonTable
                columns={columns}
                dataSource={rows}
                loading={usageScannersLoading}
                rowKey={(scanner) => scanner.id}
                emptyState={
                    <>
                        No spend this billing period yet. Costs appear here once scanners produce observations.{' '}
                        <VisionDocsLink page="quota-and-limits" dataAttr="vision-empty-docs-link-usage-table">
                            Learn how credits and limits work
                        </VisionDocsLink>
                    </>
                }
                footer={
                    hiddenCount > 0 ? (
                        <div className="px-3 py-2 text-xs text-secondary">
                            {hiddenCount} scanner{hiddenCount === 1 ? '' : 's'} with no spend or estimate this billing
                            period
                        </div>
                    ) : undefined
                }
            />
        </div>
    )
}
