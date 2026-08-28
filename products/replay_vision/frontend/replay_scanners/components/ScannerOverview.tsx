import { useActions, useValues } from 'kea'

import { IconPeople } from '@posthog/icons'
import { LemonButton, LemonTag, Link, Spinner } from '@posthog/lemon-ui'
import { BarChart } from '@posthog/quill-charts'

import { useChartConfig, useChartTheme } from 'lib/charts/hooks'
import { LemonProgress } from 'lib/lemon-ui/LemonProgress'
import { pluralize } from 'lib/utils/strings'
import { urls } from 'scenes/urls'

import { creditsToUsd, formatCreditsRange } from '../../utils/credits'
import { replayScannerLogic } from '../replayScannerLogic'
import { ReplayScannerTab, replayScannerSceneLogic } from '../replayScannerSceneLogic'
import { scannerOverviewLogic } from '../scannerOverviewLogic'
import { scannerSelfDrivingStatsLogic } from '../scannerSelfDrivingStatsLogic'
import { ScannerType } from '../types'
import { ScannerInsightsChart } from './ScannerInsightsChart'
import { ScannerOverviewFilters } from './ScannerOverviewFilters'

function OverviewPanel({
    title,
    subtitle,
    disabled,
    fill,
    children,
}: {
    title: string
    subtitle?: React.ReactNode
    disabled?: boolean
    fill?: boolean
    children: React.ReactNode
}): JSX.Element {
    return (
        <div
            className={`border rounded p-4 space-y-3 ${fill ? 'h-full flex flex-col' : ''} ${
                disabled ? 'bg-surface-secondary opacity-60' : 'bg-surface-primary'
            }`}
        >
            <div className="flex items-baseline justify-between gap-2">
                <span className="text-sm font-medium">{title}</span>
                {subtitle && <span className="text-xs text-muted tabular-nums">{subtitle}</span>}
            </div>
            {children}
        </div>
    )
}

// Spinner while stats load, otherwise the empty-state message — shared by the type-specific overview panels.
function PanelEmpty({ loading, message }: { loading: boolean; message: string }): JSX.Element {
    if (loading) {
        return (
            <div className="flex items-center justify-center py-6 text-muted">
                <Spinner />
            </div>
        )
    }
    return <div className="text-muted text-sm">{message}</div>
}

// Cap the rows so a panel can't outgrow the one beside it.
const RANKED_ROWS = 5

/**
 * Two row shapes, because the terms differ in kind:
 * - `tag` renders short vocabulary terms as pills, which is what marks them as tags rather than prose.
 * - `phrase` renders model-written sentences as plain text with the bar behind the row, so they wrap
 *   instead of being truncated into a pill.
 */
type RankedTermVariant = 'tag' | 'phrase'

function RankedTermList({
    ranked,
    loading,
    emptyMessage,
    variant,
    renderAction,
}: {
    ranked: [string, number][]
    loading: boolean
    emptyMessage: string
    variant: RankedTermVariant
    renderAction?: (term: string) => JSX.Element
}): JSX.Element {
    if (ranked.length === 0) {
        return <PanelEmpty loading={loading} message={emptyMessage} />
    }
    const top = ranked.slice(0, RANKED_ROWS)
    const maxCount = top[0][1]
    // When no term repeats, every bar is full width and falsely reads as "these all dominate", so drop the bars.
    const showBars = maxCount > 1
    const percent = (count: number): number => Math.round((count / maxCount) * 100)

    if (variant === 'tag') {
        return (
            <div className="space-y-1.5">
                {top.map(([term, count]) => (
                    <div key={term} className="flex items-center gap-2">
                        {/* Fixed-width label column so every bar shares the same left edge and their lengths stay comparable. */}
                        <div className="w-24 sm:w-40 shrink-0 flex">
                            <LemonTag type="option" title={term} className="max-w-full truncate">
                                {term}
                            </LemonTag>
                        </div>
                        {showBars ? (
                            <LemonProgress percent={percent(count)} className="flex-1" />
                        ) : (
                            <div className="flex-1" />
                        )}
                        <span className="text-xs text-muted tabular-nums text-right whitespace-nowrap shrink-0 w-12">
                            {count.toLocaleString()}
                        </span>
                        {renderAction?.(term)}
                    </div>
                ))}
            </div>
        )
    }

    return (
        <div className="space-y-1">
            {top.map(([term, count]) => (
                <div key={term} className="relative rounded overflow-hidden">
                    {showBars && (
                        <div
                            className="absolute inset-y-0 left-0 bg-accent-highlight-secondary"
                            // Width is data-derived, so it can't live in a class.
                            // eslint-disable-next-line react/forbid-dom-props
                            style={{ width: `${percent(count)}%` }}
                        />
                    )}
                    <div className="relative flex items-baseline justify-between gap-2 px-2 py-1">
                        <span className="text-xs">{term}</span>
                        <div className="flex items-center gap-1 shrink-0">
                            <span className="text-xs font-medium tabular-nums">{count.toLocaleString()}</span>
                            {renderAction?.(term)}
                        </div>
                    </div>
                </div>
            ))}
        </div>
    )
}

function ImpactOverview({ scannerId }: { scannerId: string }): JSX.Element | null {
    const { scanner, overviewImpact, overviewImpactLoading } = useValues(scannerOverviewLogic({ scannerId }))
    // Cohort creation is a scanner-level action, independent of the overview's filter set.
    const { affectedCohortLoading } = useValues(replayScannerLogic({ id: scannerId }))
    const { saveAffectedCohort } = useActions(replayScannerLogic({ id: scannerId }))

    // Impact needs a per-type predicate; only the monitor one (verdict-yes) exists without a qualifier.
    if (scanner?.scanner_type !== 'monitor') {
        return null
    }
    if (!overviewImpact || overviewImpact.affected_sessions === 0) {
        return (
            <OverviewPanel title="Impact" fill>
                <PanelEmpty
                    loading={overviewImpactLoading}
                    message={
                        overviewImpact
                            ? `No affected sessions in the last ${overviewImpact.window_days} days.`
                            : "Couldn't load impact counts."
                    }
                />
            </OverviewPanel>
        )
    }
    return (
        <OverviewPanel title="Impact" subtitle={`last ${overviewImpact.window_days} days`} fill>
            <div className="flex flex-wrap items-center justify-between gap-4">
                <div className="text-sm">
                    Matched{' '}
                    <strong className="tabular-nums">{overviewImpact.affected_sessions.toLocaleString()}</strong>{' '}
                    session{overviewImpact.affected_sessions === 1 ? '' : 's'} from{' '}
                    <strong className="tabular-nums">{overviewImpact.affected_users.toLocaleString()}</strong> user
                    {overviewImpact.affected_users === 1 ? '' : 's'}
                    {overviewImpact.sessions_without_user > 0 && (
                        <span className="text-muted"> ({overviewImpact.sessions_without_user} without a user)</span>
                    )}
                </div>
                <LemonButton
                    type="secondary"
                    size="small"
                    icon={<IconPeople />}
                    onClick={() => saveAffectedCohort()}
                    loading={affectedCohortLoading}
                    disabledReason={overviewImpact.affected_users === 0 ? 'No users to save' : undefined}
                    data-attr="vision-save-affected-cohort"
                    className="shrink-0"
                >
                    Save as cohort
                </LemonButton>
            </div>
        </OverviewPanel>
    )
}

// One stage of the self-driving funnel: a big count over a muted label, matching the panel grid density.
function SelfDrivingStage({ count, label }: { count: number; label: string }): JSX.Element {
    return (
        <div className="flex flex-col">
            <span className="text-lg font-semibold tabular-nums">{count.toLocaleString()}</span>
            <span className="text-xs text-muted">{label}</span>
        </div>
    )
}

function SelfDrivingOverview({ scannerId }: { scannerId: string }): JSX.Element {
    const { scanner } = useValues(replayScannerLogic({ id: scannerId }))
    const { selfDrivingStats, selfDrivingStatsLoading } = useValues(scannerSelfDrivingStatsLogic({ scannerId }))

    // Unresolved data renders as loading, never as the off-state nudge or the empty state.
    if (!scanner || (selfDrivingStatsLoading && !selfDrivingStats)) {
        return (
            <OverviewPanel title="Self-driving">
                <PanelEmpty loading message="" />
            </OverviewPanel>
        )
    }
    // Historical signals from before the toggle was turned off still count, so the off-state
    // nudge only replaces the funnel when there is nothing to show.
    if (!scanner.emits_signals && (!selfDrivingStats || selfDrivingStats.signals_emitted === 0)) {
        return (
            <OverviewPanel title="Self-driving" disabled>
                <div className="text-muted text-sm">
                    This scanner doesn't emit signals. Turn on self-driving in the{' '}
                    <Link to={urls.replayVisionScannerConfigure(scannerId)}>scanner's configuration</Link> to feed its
                    findings into Signals, where agents investigate and draft pull requests.
                </div>
            </OverviewPanel>
        )
    }
    if (!selfDrivingStats || selfDrivingStats.signals_emitted === 0) {
        return (
            <OverviewPanel title="Self-driving">
                <PanelEmpty
                    loading={selfDrivingStatsLoading}
                    message={
                        selfDrivingStats
                            ? 'No signals emitted yet. Findings flow into Signals as sessions are scanned.'
                            : "Couldn't load self-driving stats."
                    }
                />
            </OverviewPanel>
        )
    }
    return (
        <OverviewPanel title="Self-driving" subtitle="all time">
            {/* Capped so the four stages read as one row on wide screens instead of drifting apart. */}
            <div className="grid grid-cols-4 gap-4 max-w-3xl" data-attr="vision-self-driving-funnel">
                <SelfDrivingStage
                    count={selfDrivingStats.signals_emitted}
                    label={pluralize(selfDrivingStats.signals_emitted, 'signal emitted', 'signals emitted', false)}
                />
                <SelfDrivingStage
                    count={selfDrivingStats.reports_contributed}
                    label={pluralize(
                        selfDrivingStats.reports_contributed,
                        'report contributed to',
                        'reports contributed to',
                        false
                    )}
                />
                <SelfDrivingStage
                    count={selfDrivingStats.prs_opened}
                    label={pluralize(selfDrivingStats.prs_opened, 'PR opened', 'PRs opened', false)}
                />
                <SelfDrivingStage
                    count={selfDrivingStats.prs_merged}
                    label={pluralize(selfDrivingStats.prs_merged, 'PR merged', 'PRs merged', false)}
                />
            </div>
            <div className="text-xs text-muted">
                A report can combine signals from several scanners and other sources, so these are contributions, not
                sole causes.
            </div>
        </OverviewPanel>
    )
}

function MonitorOverview({ scannerId }: { scannerId: string }): JSX.Element {
    const { monitorStats, hasActiveOverviewFilters, overviewStatsApiLoading } = useValues(
        scannerOverviewLogic({ scannerId })
    )
    const { yesTotal, noTotal, inconclusiveTotal } = monitorStats
    const total = yesTotal + noTotal + inconclusiveTotal
    if (total === 0) {
        return (
            <OverviewPanel title="Verdict mix" fill>
                <PanelEmpty
                    loading={overviewStatsApiLoading}
                    message={hasActiveOverviewFilters ? 'No verdicts match the current filter.' : 'No verdicts yet.'}
                />
            </OverviewPanel>
        )
    }
    const yesPct = Math.round((yesTotal / total) * 100)
    const noPct = Math.round((noTotal / total) * 100)
    const inconclusivePct = Math.max(0, 100 - yesPct - noPct)

    return (
        <OverviewPanel title="Verdict mix" subtitle={`${total} verdict${total === 1 ? '' : 's'}`} fill>
            <LemonProgress percent={yesPct} />
            <div className="flex flex-wrap items-center gap-4 text-sm">
                <span className="flex items-center gap-2">
                    <LemonTag type="highlight">Yes</LemonTag>
                    <span className="tabular-nums">
                        {yesTotal} ({yesPct}%)
                    </span>
                </span>
                <span className="flex items-center gap-2">
                    <LemonTag type="default">No</LemonTag>
                    <span className="tabular-nums">
                        {noTotal} ({noPct}%)
                    </span>
                </span>
                {inconclusiveTotal > 0 && (
                    <span className="flex items-center gap-2">
                        <LemonTag type="muted">Inconclusive</LemonTag>
                        <span className="tabular-nums">
                            {inconclusiveTotal} ({inconclusivePct}%)
                        </span>
                    </span>
                )}
            </div>
        </OverviewPanel>
    )
}

function ClassifierOverview({ scannerId }: { scannerId: string }): JSX.Element | null {
    const { scanner, classifierTagStats, hasActiveOverviewFilters, overviewStatsApiLoading } = useValues(
        scannerOverviewLogic({ scannerId })
    )
    // Cohort creation is a scanner-level action, independent of the overview's filter set.
    const { affectedCohortLoading, savingCohortTag } = useValues(replayScannerLogic({ id: scannerId }))
    const { saveAffectedCohort } = useActions(replayScannerLogic({ id: scannerId }))
    const { fixedRanked, freeformRanked } = classifierTagStats
    // Wait for the scanner config — without it `freeformAllowed` defaults to `false` and the panel flashes the
    // "disabled" copy while the config is still loading.
    if (!scanner || scanner.scanner_type !== 'classifier') {
        return null
    }
    const freeformAllowed = !!scanner.scanner_config.allow_freeform_tags
    const fixedEmpty = hasActiveOverviewFilters
        ? 'No configured categories match the current filter.'
        : 'No configured categories emitted yet.'
    const freeformEmpty = hasActiveOverviewFilters
        ? 'No freeform categories match the current filter.'
        : 'No freeform categories emitted yet.'

    const cohortAction = (tag: string): JSX.Element => (
        <LemonButton
            type="secondary"
            size="xsmall"
            icon={<IconPeople />}
            tooltip={`Save users in category "${tag}" from the last 30 days as a cohort`}
            onClick={() => saveAffectedCohort(tag)}
            loading={affectedCohortLoading && savingCohortTag === tag}
            disabledReason={
                affectedCohortLoading && savingCohortTag !== tag ? 'Another cohort is being created' : undefined
            }
            data-attr="vision-save-tag-cohort"
        >
            Save as cohort
        </LemonButton>
    )

    return (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            <OverviewPanel title="Top configured categories" subtitle="from the categories you defined" fill>
                <RankedTermList
                    ranked={fixedRanked}
                    loading={overviewStatsApiLoading}
                    emptyMessage={fixedEmpty}
                    variant="tag"
                    renderAction={cohortAction}
                />
            </OverviewPanel>

            <OverviewPanel
                title="Top freeform categories"
                subtitle={freeformAllowed ? 'outside the categories you defined' : 'disabled'}
                disabled={!freeformAllowed}
                fill
            >
                {freeformAllowed ? (
                    <RankedTermList
                        ranked={freeformRanked}
                        loading={overviewStatsApiLoading}
                        emptyMessage={freeformEmpty}
                        variant="tag"
                        renderAction={cohortAction}
                    />
                ) : (
                    <div className="text-muted text-sm">
                        Freeform categories are disabled for this scanner, so the model can only pick from the
                        categories you defined. Enable "Allow freeform categories" in the scanner config to let it
                        propose new ones.
                    </div>
                )}
            </OverviewPanel>
        </div>
    )
}

function CreditLimitOverview({ scannerId }: { scannerId: string }): JSX.Element | null {
    const { creditLimitStats } = useValues(scannerOverviewLogic({ scannerId }))
    if (!creditLimitStats) {
        return null
    }
    const { used, limit, usedPct, limitReached } = creditLimitStats
    return (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            <div className="min-w-0">
                <OverviewPanel
                    title="Spend against limit"
                    subtitle={limitReached ? <LemonTag type="danger">Limit reached</LemonTag> : `${usedPct}%`}
                    fill
                >
                    <LemonProgress percent={usedPct} strokeColor={limitReached ? 'var(--danger)' : undefined} />
                    <div className="text-sm tabular-nums">
                        {formatCreditsRange(used, limit)} (≈ {creditsToUsd(limit)} per period)
                    </div>
                    {limitReached && (
                        // The tag can appear below 100%: a scanner stops as soon as what's left can't cover a whole
                        // scan, so the copy has to explain that rather than claim the budget is fully spent.
                        <div className="text-xs text-muted">
                            What's left won't cover another scan, so this scanner has stopped until its limit resets at
                            the start of the next billing period. Sessions skipped while capped are not scanned later.
                        </div>
                    )}
                </OverviewPanel>
            </div>
        </div>
    )
}

function ScorerOverview({ scannerId }: { scannerId: string }): JSX.Element {
    const { scorerSummary, scorerHistogram, hasActiveOverviewFilters, overviewStatsApiLoading } = useValues(
        scannerOverviewLogic({ scannerId })
    )
    const theme = useChartTheme()
    const config = useChartConfig(() => ({ showGrid: false }), [])
    if (!scorerSummary || !scorerHistogram) {
        return (
            <OverviewPanel title="Score distribution">
                <PanelEmpty
                    loading={overviewStatsApiLoading}
                    message={
                        hasActiveOverviewFilters
                            ? 'No scored observations match the current filter.'
                            : 'No scored observations yet.'
                    }
                />
            </OverviewPanel>
        )
    }
    return (
        <OverviewPanel title="Score distribution" subtitle={`${scorerSummary.count} scored`} fill>
            <div className="flex-1 min-h-40 flex flex-col">
                <BarChart
                    labels={scorerHistogram.labels}
                    series={[{ key: 'count', label: 'Sessions', color: theme.colors[0], data: scorerHistogram.counts }]}
                    config={config}
                    theme={theme}
                />
            </div>
            <div className="flex flex-wrap justify-between gap-x-4 gap-y-1 text-xs text-muted tabular-nums pt-1 border-t">
                <span>min {scorerSummary.min.toFixed(1)}</span>
                <span>median {scorerSummary.median.toFixed(1)}</span>
                <span>avg {scorerSummary.mean.toFixed(1)}</span>
                <span>max {scorerSummary.max.toFixed(1)}</span>
            </div>
        </OverviewPanel>
    )
}

function SummarizerOverview({ scannerId }: { scannerId: string }): JSX.Element | null {
    const { scanner, summarizerFacetStats, hasActiveOverviewFilters, overviewStatsApiLoading } = useValues(
        scannerOverviewLogic({ scannerId })
    )
    if (!scanner || scanner.scanner_type !== 'summarizer') {
        return null
    }
    const { frictionRanked, keywordRanked, totalSucceeded, totalWithFriction } = summarizerFacetStats
    const frictionEmpty = hasActiveOverviewFilters
        ? 'No friction points match the current filter.'
        : 'No friction points reported yet. They appear as summaries accumulate.'
    const keywordEmpty = hasActiveOverviewFilters
        ? 'No keywords match the current filter.'
        : 'No keywords reported yet. They appear as summaries accumulate.'

    const summaries = (count: number): string => `${count.toLocaleString()} summar${count === 1 ? 'y' : 'ies'}`
    // Both subtitles use the same succeeded-summary denominator so the two panels stay comparable.
    const frictionSubtitle =
        totalSucceeded > 0
            ? `${totalWithFriction.toLocaleString()} of ${summaries(totalSucceeded)} (${Math.round(
                  (totalWithFriction / totalSucceeded) * 100
              )}%)`
            : undefined
    const keywordSubtitle = totalSucceeded > 0 ? `from ${summaries(totalSucceeded)}` : undefined
    return (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            <OverviewPanel title="Top friction points" subtitle={frictionSubtitle} fill>
                <RankedTermList
                    ranked={frictionRanked}
                    loading={overviewStatsApiLoading}
                    emptyMessage={frictionEmpty}
                    variant="phrase"
                />
            </OverviewPanel>
            <OverviewPanel title="Common keywords" subtitle={keywordSubtitle} fill>
                <RankedTermList
                    ranked={keywordRanked}
                    loading={overviewStatsApiLoading}
                    emptyMessage={keywordEmpty}
                    variant="tag"
                />
            </OverviewPanel>
        </div>
    )
}

// The interstitial a just-created scanner shows instead of the filters + charts, whose "no matching
// events" empty state would wrongly suggest the user's setup is broken while the first sweep runs.
// It also hides the overview's reload buttons, so when the background checks keep failing it has to
// surface that itself and offer a retry.
function FirstScanPendingPanel({ scannerId }: { scannerId: string }): JSX.Element {
    const { setActiveTab } = useActions(replayScannerSceneLogic)
    const { firstScanCheckFailing, overviewStatsApiLoading } = useValues(scannerOverviewLogic({ scannerId }))
    const { loadOverviewStats } = useActions(scannerOverviewLogic({ scannerId }))
    return (
        <div
            className="border rounded bg-surface-primary p-6 flex flex-col items-center gap-2 text-center"
            data-attr="vision-first-scan-pending"
        >
            {!firstScanCheckFailing && <Spinner className="text-2xl" />}
            <div className="font-semibold">First scan in progress</div>
            <div className="text-muted text-sm max-w-md">
                {firstScanCheckFailing
                    ? "We couldn't check for results. We'll keep retrying, or you can retry now."
                    : 'This scanner picks up new recordings on a schedule. Results usually appear within 15 minutes.'}
            </div>
            {firstScanCheckFailing && (
                <LemonButton
                    type="secondary"
                    size="small"
                    loading={overviewStatsApiLoading}
                    onClick={() => loadOverviewStats()}
                    data-attr="vision-first-scan-pending-retry"
                >
                    Retry
                </LemonButton>
            )}
            <LemonButton
                type="secondary"
                size="small"
                onClick={() => setActiveTab(ReplayScannerTab.OnDemand)}
                data-attr="vision-first-scan-pending-scan-now"
            >
                Scan a recording now
            </LemonButton>
        </div>
    )
}

export function ScannerOverview({ scannerId }: { scannerId: string }): JSX.Element | null {
    const { scanner } = useValues(replayScannerLogic({ id: scannerId }))
    const { firstScanPending } = useValues(scannerOverviewLogic({ scannerId }))
    if (!scanner) {
        return null
    }
    if (firstScanPending) {
        return <FirstScanPendingPanel scannerId={scannerId} />
    }
    const scannerType: ScannerType = scanner.scanner_type
    const typeOverview =
        scannerType === 'monitor' ? (
            <MonitorOverview scannerId={scannerId} />
        ) : scannerType === 'classifier' ? (
            <ClassifierOverview scannerId={scannerId} />
        ) : scannerType === 'scorer' ? (
            <ScorerOverview scannerId={scannerId} />
        ) : scannerType === 'summarizer' ? (
            <SummarizerOverview scannerId={scannerId} />
        ) : null

    // Scorer puts its line chart and score-distribution histogram side by side to reclaim vertical space.
    let body: JSX.Element
    if (scannerType === 'scorer') {
        body = (
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
                {/* min-w-0 lets the canvas charts shrink inside their grid tracks instead of overflowing */}
                <div className="min-w-0">
                    <ScannerInsightsChart scannerId={scannerId} scannerType={scannerType} />
                </div>
                {/* The histogram fills to match the taller line chart, so the row has no dead space (stretch is the grid default). */}
                <div className="min-w-0">{typeOverview}</div>
            </div>
        )
    } else if (scannerType !== 'monitor') {
        // Impact only exists for monitors; other types keep their overview at full width.
        body = (
            <div className="space-y-4">
                <ScannerInsightsChart scannerId={scannerId} scannerType={scannerType} />
                {typeOverview}
            </div>
        )
    } else {
        body = (
            <div className="space-y-4">
                <ScannerInsightsChart scannerId={scannerId} scannerType={scannerType} />
                <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
                    {typeOverview && <div className="min-w-0">{typeOverview}</div>}
                    <div className="min-w-0">
                        <ImpactOverview scannerId={scannerId} />
                    </div>
                </div>
            </div>
        )
    }

    return (
        <div className="flex flex-col gap-4">
            <ScannerOverviewFilters scannerId={scannerId} />
            {body}
            <SelfDrivingOverview scannerId={scannerId} />
            <CreditLimitOverview scannerId={scannerId} />
        </div>
    )
}
