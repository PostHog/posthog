import { useActions, useValues } from 'kea'

import { LemonButton, LemonCard, LemonSwitch, Link, Spinner, Tooltip } from '@posthog/lemon-ui'

import { LemonProgress } from 'lib/lemon-ui/LemonProgress'
import { LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { LemonTable } from 'lib/lemon-ui/LemonTable'
import { pluralize } from 'lib/utils/strings'
import { urls } from 'scenes/urls'

import { ProductKey } from '~/queries/schema/schema-general'

import { VisionDocsLink } from '../../components/DocsLink'
import { CreditPriceNote } from '../../components/PricingLink'
import { visionQuotaLogic } from '../../logics/visionQuotaLogic'
import { getReplayVisionEditDisabledReason } from '../../utils/accessControl'
import {
    creditsToUsd,
    formatCreditCount,
    formatCreditNumber,
    formatCreditsMaybeUsd,
    formatCreditsRange,
} from '../../utils/credits'
import { verdictColorVar, verdictTextClass } from '../../utils/spendVerdict'
import { STARTUP_CAP_EXPLANATION } from '../../utils/startupCap'
import { ReplayScanner } from '../types'
import { visionUsageLogic } from '../visionUsageLogic'
import { SpendTrajectoryChart } from './SpendTrajectoryChart'

const ORG_WIDE_NOTE = 'Spend and limits are shared by every project in the organization.'
const BILLING_URL = urls.organizationBilling([ProductKey.REPLAY_VISION])

function TilePlaceholder({ loading }: { loading: boolean }): JSX.Element {
    return <span className="text-2xl font-semibold">{loading ? <Spinner /> : '—'}</span>
}

export function VisionUsageTab(): JSX.Element {
    const {
        usageRows,
        usageScannersLoading,
        hiddenScannerCount,
        usageRowsTotalCredits,
        togglingScannerIds,
        spendSeries,
        spendSeriesLoading,
        spendSeriesFailed,
        verdict,
        resetsOn,
        daysToReset,
        projectedTotalCredits,
        projectedPctOfLimit,
    } = useValues(visionUsageLogic)
    const { toggleScannerEnabled, loadSpendSeries } = useActions(visionUsageLogic)
    const {
        displayQuota: quota,
        quotaLoading,
        showUsd,
        billedCredits,
        billedLimitCredits,
        showStartupCap,
    } = useValues(visionQuotaLogic)

    const statusText = verdictTextClass(verdict.kind)
    const hasCap = verdict.hasCap
    const capDate =
        verdict.kind === 'danger' && verdict.projection.capReachDate
            ? verdict.projection.capReachDate.format('MMM D')
            : null
    const spendTooltip = quota
        ? `${ORG_WIDE_NOTE}${
              showUsd
                  ? ` ≈ ${creditsToUsd(billedCredits)} billed${hasCap ? ` of ${creditsToUsd(billedLimitCredits)}` : ''}.`
                  : ''
          }${showStartupCap ? ` ${STARTUP_CAP_EXPLANATION}` : ''}`
        : undefined

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
                const sharePct =
                    usageRowsTotalCredits > 0
                        ? Math.round((scanner.credits_this_month / usageRowsTotalCredits) * 100)
                        : 0
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
            tooltip:
                "Credits per 30 days based on the scanner's filters and sampling. Updates when the scanner is saved.",
            render: (_, scanner) => {
                if (!scanner.enabled || scanner.estimated_monthly_credits === null) {
                    return <div className="text-secondary text-right">—</div>
                }
                const stale = !scanner.estimated_at
                return (
                    <Tooltip title={stale ? 'The estimate is being recomputed after a change.' : undefined}>
                        <div className="text-sm tabular-nums text-secondary text-right whitespace-nowrap">
                            ~{formatCreditCount(scanner.estimated_monthly_credits)}
                            {stale ? ' (updating)' : ''}
                        </div>
                    </Tooltip>
                )
            },
        },
    ]

    return (
        <div className="@container flex flex-col gap-4">
            <div className="grid grid-cols-1 @md:grid-cols-2 @xl:grid-cols-4 gap-4">
                <LemonCard hoverEffect={false} className="p-4 flex flex-col gap-1" data-attr="vision-usage-tile-spent">
                    <span className="text-muted text-xs font-medium uppercase">Spent</span>
                    {quota ? (
                        <Tooltip title={spendTooltip}>
                            <span className="text-2xl font-semibold tabular-nums">
                                {formatCreditNumber(quota.credits_used)}{' '}
                                <span className="text-sm font-normal text-secondary">credits</span>
                            </span>
                        </Tooltip>
                    ) : (
                        <TilePlaceholder loading={quotaLoading} />
                    )}
                    {quota && showUsd && (
                        <span className="text-xs text-secondary tabular-nums">
                            ≈ {creditsToUsd(billedCredits)} billed
                        </span>
                    )}
                    <span className="text-xs text-secondary">
                        <CreditPriceNote dataAttr="vision-pricing-link-usage" />
                    </span>
                </LemonCard>
                <LemonCard
                    hoverEffect={false}
                    className="p-4 flex flex-col gap-1"
                    data-attr="vision-usage-tile-projected"
                >
                    <span className="text-muted text-xs font-medium uppercase">
                        Projected by {resetsOn ? resetsOn.format('MMM D') : 'period end'}
                    </span>
                    {quota && projectedTotalCredits !== null ? (
                        <span className={`text-2xl font-semibold tabular-nums ${statusText}`}>
                            {formatCreditNumber(projectedTotalCredits)}{' '}
                            <span className="text-sm font-normal text-secondary">credits</span>
                        </span>
                    ) : (
                        <TilePlaceholder loading={quotaLoading} />
                    )}
                    <span
                        className={`text-xs tabular-nums ${verdict.kind === 'paused' || capDate ? 'text-danger' : 'text-secondary'}`}
                    >
                        {verdict.kind === 'paused'
                            ? 'limit reached, scanning is paused'
                            : capDate
                              ? `hits the limit around ${capDate}`
                              : projectedPctOfLimit !== null
                                ? `${projectedPctOfLimit}% of limit`
                                : 'no limit set'}
                    </span>
                    {(verdict.kind === 'paused' || capDate !== null) && (
                        <span className="text-xs">
                            <Link to={BILLING_URL}>Increase your spending limit</Link> to keep scanning.
                        </span>
                    )}
                </LemonCard>
                <LemonCard hoverEffect={false} className="p-4 flex flex-col gap-1" data-attr="vision-usage-tile-limit">
                    <span className="text-muted text-xs font-medium uppercase">Monthly limit</span>
                    {quota ? (
                        <Tooltip title={ORG_WIDE_NOTE}>
                            <span className="text-2xl font-semibold tabular-nums">
                                {hasCap ? formatCreditNumber(quota.credit_limit ?? 0) : 'None set'}
                                {hasCap && <span className="text-sm font-normal text-secondary"> credits</span>}
                            </span>
                        </Tooltip>
                    ) : (
                        <TilePlaceholder loading={quotaLoading} />
                    )}
                    <span className="text-xs text-secondary tabular-nums">
                        {hasCap ? (
                            <>
                                {showUsd ? `≈ ${creditsToUsd(billedLimitCredits)} billed at most · ` : ''}
                                <Link to={BILLING_URL}>change</Link>
                            </>
                        ) : (
                            <>
                                <Link to={BILLING_URL}>Set a spending limit</Link> to control spend.
                            </>
                        )}
                    </span>
                </LemonCard>
                <LemonCard hoverEffect={false} className="p-4 flex flex-col gap-1" data-attr="vision-usage-tile-resets">
                    <span className="text-muted text-xs font-medium uppercase">Resets in</span>
                    <span className="text-2xl font-semibold tabular-nums">
                        {daysToReset !== null ? pluralize(daysToReset, 'day') : '—'}
                    </span>
                    <span className="text-xs text-secondary">{resetsOn ? resetsOn.format('MMMM D') : ''}</span>
                </LemonCard>
            </div>

            <LemonCard hoverEffect={false} className="p-4 flex flex-col gap-2">
                <div className="flex flex-wrap items-baseline justify-between gap-2">
                    <h3 className="text-base font-semibold m-0">Spend this period</h3>
                    {quota && (
                        <span className="text-xs text-secondary tabular-nums">
                            {hasCap
                                ? formatCreditsRange(quota.credits_used, quota.credit_limit ?? 0)
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
                            projectedTotal={projectedTotalCredits ?? quota.credits_used}
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
                    <div className="flex items-center justify-center gap-2 h-40 text-sm text-secondary">
                        {spendSeriesLoading || quotaLoading ? (
                            <Spinner />
                        ) : spendSeriesFailed ? (
                            <>
                                <span>Couldn't load spend data.</span>
                                <LemonButton size="small" type="secondary" onClick={() => loadSpendSeries()}>
                                    Try again
                                </LemonButton>
                            </>
                        ) : (
                            <span>Spend data is unavailable.</span>
                        )}
                    </div>
                )}
            </LemonCard>

            <LemonTable
                columns={columns}
                dataSource={usageRows}
                loading={usageScannersLoading}
                rowKey={(scanner) => scanner.id}
                emptyState={
                    <div className="text-sm text-secondary">
                        No spend this billing period yet. Costs appear here once scanners produce observations.{' '}
                        <VisionDocsLink page="quota-and-limits" dataAttr="vision-empty-docs-link-usage-table">
                            Learn how credits and limits work
                        </VisionDocsLink>
                    </div>
                }
                footer={
                    hiddenScannerCount > 0 ? (
                        <div className="px-3 py-2 text-xs text-secondary">
                            {pluralize(hiddenScannerCount, 'scanner')} with no spend or estimate this billing period
                        </div>
                    ) : undefined
                }
            />
        </div>
    )
}
