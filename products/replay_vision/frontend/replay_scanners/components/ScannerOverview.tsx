import { useActions, useValues } from 'kea'

import { IconPeople } from '@posthog/icons'
import { LemonButton, LemonTag, Spinner } from '@posthog/lemon-ui'
import { BarChart } from '@posthog/quill-charts'

import { useChartConfig, useChartTheme } from 'lib/charts/hooks'
import { LemonProgress } from 'lib/lemon-ui/LemonProgress'

import { replayScannerLogic } from '../replayScannerLogic'
import { scannerOverviewLogic } from '../scannerOverviewLogic'
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
                        <div className="w-40 shrink-0 flex">
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
            <div className="flex items-center justify-between gap-4">
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
        ? 'No fixed-vocabulary tags match the current filter.'
        : 'No fixed-vocabulary tags emitted yet.'
    const freeformEmpty = hasActiveOverviewFilters
        ? 'No freeform tags match the current filter.'
        : 'No freeform tags emitted yet.'

    const cohortAction = (tag: string): JSX.Element => (
        <LemonButton
            size="xsmall"
            icon={<IconPeople />}
            tooltip={`Save users tagged "${tag}" in the last 30 days as a cohort`}
            onClick={() => saveAffectedCohort(tag)}
            loading={affectedCohortLoading && savingCohortTag === tag}
            disabledReason={
                affectedCohortLoading && savingCohortTag !== tag ? 'Another cohort is being created' : undefined
            }
            data-attr="vision-save-tag-cohort"
        />
    )

    return (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            <OverviewPanel title="Top fixed tags" subtitle="from configured vocabulary" fill>
                <RankedTermList
                    ranked={fixedRanked}
                    loading={overviewStatsApiLoading}
                    emptyMessage={fixedEmpty}
                    variant="tag"
                    renderAction={cohortAction}
                />
            </OverviewPanel>

            <OverviewPanel
                title="Top freeform tags"
                subtitle={freeformAllowed ? 'outside configured vocabulary' : 'disabled'}
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
                        Freeform tags are disabled for this scanner, so the model can only pick from your configured
                        vocabulary. Enable "Allow freeform tags" in the scanner config to let it propose new ones.
                    </div>
                )}
            </OverviewPanel>
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
            <div className="flex justify-between gap-4 text-xs text-muted tabular-nums pt-1 border-t">
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

export function ScannerOverview({ scannerId }: { scannerId: string }): JSX.Element | null {
    const { scanner } = useValues(replayScannerLogic({ id: scannerId }))
    if (!scanner) {
        return null
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
        </div>
    )
}
