import { useActions, useValues } from 'kea'

import { IconPeople } from '@posthog/icons'
import { LemonButton, LemonTag, LemonTagType, Spinner } from '@posthog/lemon-ui'
import { BarChart } from '@posthog/quill-charts'

import { useChartConfig, useChartTheme } from 'lib/charts/hooks'
import { LemonProgress } from 'lib/lemon-ui/LemonProgress'
import { pluralize } from 'lib/utils/strings'

import { type AffectedCohortQualifier, type ObservationVerdictValue, replayScannerLogic } from '../replayScannerLogic'
import { ReplayScannerTab, replayScannerSceneLogic } from '../replayScannerSceneLogic'
import { scannerOverviewLogic } from '../scannerOverviewLogic'
import { ScannerType } from '../types'
import { ScannerInsightsChart } from './ScannerInsightsChart'
import { ScannerOverviewFilters } from './ScannerOverviewFilters'
import { ScannerScoutCard } from './ScannerScoutCard'
import { ScannerSelfDrivingCard } from './ScannerSelfDrivingCard'
import { ScannerSetupCard } from './ScannerSetupCard'
import { ScannerStatusStrip } from './ScannerStatusStrip'

function FindingsSection({
    title,
    subtitle,
    children,
}: {
    title: string
    subtitle?: React.ReactNode
    children: React.ReactNode
}): JSX.Element {
    return (
        <div className="min-w-0 flex flex-col gap-3">
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

function RankedTermList({
    ranked,
    loading,
    emptyMessage,
    renderAction,
}: {
    ranked: [string, number][]
    loading: boolean
    emptyMessage: string
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

const VERDICT_ROWS: { verdict: ObservationVerdictValue; label: string; tagType: LemonTagType }[] = [
    { verdict: 'yes', label: 'Yes', tagType: 'highlight' },
    { verdict: 'no', label: 'No', tagType: 'default' },
    { verdict: 'inconclusive', label: 'Inconclusive', tagType: 'muted' },
]

function SaveCohortButton({
    scannerId,
    qualifier,
    cohortKey,
    tooltip,
    ariaLabel,
    emptyReason,
    dataAttr,
    children,
}: {
    scannerId: string
    qualifier: AffectedCohortQualifier
    cohortKey: string
    tooltip: string
    ariaLabel?: string
    emptyReason?: string
    dataAttr: string
    children?: React.ReactNode
}): JSX.Element {
    const { cohortDisabledReason } = useValues(scannerOverviewLogic({ scannerId }))
    const { saveCohort } = useActions(scannerOverviewLogic({ scannerId }))
    const { affectedCohortLoading, savingCohortKey } = useValues(replayScannerLogic({ id: scannerId }))
    return (
        <LemonButton
            type="secondary"
            size="xsmall"
            icon={<IconPeople />}
            tooltip={tooltip}
            aria-label={ariaLabel}
            onClick={() => saveCohort(qualifier)}
            loading={affectedCohortLoading && savingCohortKey === cohortKey}
            disabledReason={
                emptyReason ??
                cohortDisabledReason ??
                (affectedCohortLoading && savingCohortKey !== cohortKey ? 'Another cohort is being created' : undefined)
            }
            data-attr={dataAttr}
        >
            {children}
        </LemonButton>
    )
}

function VerdictMixOverview({ scannerId }: { scannerId: string }): JSX.Element {
    const { monitorStats, hasActiveOverviewFilters, overviewStatsApiLoading, cohortWindowDays } = useValues(
        scannerOverviewLogic({ scannerId })
    )
    const counts: Record<ObservationVerdictValue, number> = {
        yes: monitorStats.yesTotal,
        no: monitorStats.noTotal,
        inconclusive: monitorStats.inconclusiveTotal,
    }
    const total = counts.yes + counts.no + counts.inconclusive
    if (total === 0) {
        return (
            <FindingsSection title="Verdict mix">
                <PanelEmpty
                    loading={overviewStatsApiLoading}
                    message={hasActiveOverviewFilters ? 'No verdicts match the current filter.' : 'No verdicts yet.'}
                />
            </FindingsSection>
        )
    }
    const rows = VERDICT_ROWS.filter(({ verdict }) => verdict !== 'inconclusive' || counts.inconclusive > 0)

    return (
        <FindingsSection title="Verdict mix" subtitle={pluralize(total, 'verdict')}>
            <div className="space-y-1.5">
                {rows.map(({ verdict, label, tagType }) => {
                    const count = counts[verdict]
                    const percent = Math.round((count / total) * 100)
                    return (
                        <div key={verdict} className="flex items-center gap-2">
                            <div className="w-24 shrink-0">
                                <LemonTag type={tagType}>{label}</LemonTag>
                            </div>
                            <LemonProgress percent={percent} className="flex-1" />
                            <span className="text-xs text-muted tabular-nums text-right whitespace-nowrap shrink-0 w-20">
                                {count.toLocaleString()} ({percent}%)
                            </span>
                            <SaveCohortButton
                                scannerId={scannerId}
                                qualifier={{ verdict }}
                                cohortKey={verdict}
                                tooltip={`Save users with a ${label.toLowerCase()} verdict from the last ${pluralize(cohortWindowDays, 'day')} as a cohort`}
                                emptyReason={count === 0 ? 'No sessions with this verdict' : undefined}
                                // pinned: the yes row keeps the data-attr the single cohort button shipped with.
                                dataAttr={
                                    verdict === 'yes'
                                        ? 'vision-save-affected-cohort'
                                        : `vision-save-verdict-cohort-${verdict}`
                                }
                            >
                                Save as cohort
                            </SaveCohortButton>
                        </div>
                    )
                })}
            </div>
        </FindingsSection>
    )
}

function ClassifierOverview({ scannerId }: { scannerId: string }): JSX.Element | null {
    const { scanner, classifierTagStats, hasActiveOverviewFilters, overviewStatsApiLoading, cohortWindowDays } =
        useValues(scannerOverviewLogic({ scannerId }))
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
        <SaveCohortButton
            scannerId={scannerId}
            qualifier={{ tag }}
            cohortKey={tag}
            tooltip="Save as cohort"
            ariaLabel={`Save users in category "${tag}" from the last ${pluralize(cohortWindowDays, 'day')} as a cohort`}
            dataAttr="vision-save-tag-cohort"
        />
    )

    return (
        <div className="grid grid-cols-1 @2xl:grid-cols-2 gap-x-8 gap-y-6">
            <FindingsSection title="Top configured categories" subtitle="from the categories you defined">
                <RankedTermList
                    ranked={fixedRanked}
                    loading={overviewStatsApiLoading}
                    emptyMessage={fixedEmpty}
                    renderAction={cohortAction}
                />
            </FindingsSection>

            <FindingsSection
                title="Top freeform categories"
                subtitle={freeformAllowed ? 'outside the categories you defined' : 'disabled'}
            >
                {freeformAllowed ? (
                    <RankedTermList
                        ranked={freeformRanked}
                        loading={overviewStatsApiLoading}
                        emptyMessage={freeformEmpty}
                        renderAction={cohortAction}
                    />
                ) : (
                    <div className="text-muted text-sm">
                        Freeform categories are disabled for this scanner, so the model can only pick from the
                        categories you defined. Enable "Allow freeform categories" in the scanner config to let it
                        propose new ones.
                    </div>
                )}
            </FindingsSection>
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
            <FindingsSection title="Score distribution">
                <PanelEmpty
                    loading={overviewStatsApiLoading}
                    message={
                        hasActiveOverviewFilters
                            ? 'No scored observations match the current filter.'
                            : 'No scored observations yet.'
                    }
                />
            </FindingsSection>
        )
    }
    return (
        <FindingsSection title="Score distribution" subtitle={`${scorerSummary.count} scored`}>
            <div className="h-64 flex flex-col">
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
        </FindingsSection>
    )
}

function FindingsCoverage({ scannerId }: { scannerId: string }): JSX.Element | null {
    const { coverageStats, overviewStatsApiLoading } = useValues(scannerOverviewLogic({ scannerId }))
    if (coverageStats.totalSessions > 0) {
        return (
            <div className="text-xs text-muted tabular-nums mt-0.5">
                Scanned <span className="font-semibold text-default">{coverageStats.recentSessions}</span>{' '}
                {pluralize(coverageStats.recentSessions, 'session', 'sessions', false)} in the last{' '}
                {pluralize(coverageStats.recentDays, 'day')} ·{' '}
                <span className="font-semibold text-default">{coverageStats.totalSessions}</span> total
            </div>
        )
    }
    if (overviewStatsApiLoading) {
        return (
            <div className="text-xs text-muted mt-0.5 flex items-center gap-1.5">
                <Spinner /> Loading coverage…
            </div>
        )
    }
    return null
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
                onClick={() => setActiveTab(ReplayScannerTab.Run)}
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
    const scannerType: ScannerType = scanner.scanner_type
    const typeOverview =
        scannerType === 'monitor' ? (
            <VerdictMixOverview scannerId={scannerId} />
        ) : scannerType === 'classifier' ? (
            <ClassifierOverview scannerId={scannerId} />
        ) : scannerType === 'scorer' ? (
            <ScorerOverview scannerId={scannerId} />
        ) : null

    const body = (
        <>
            <ScannerInsightsChart scannerId={scannerId} scannerType={scannerType} />
            {typeOverview && <div className="border-t pt-4">{typeOverview}</div>}
        </>
    )

    return (
        <div className="@container">
            {/* The second row takes any extra height, so a side column taller than the main one can't open a gap under the status. */}
            <div className="grid grid-cols-1 @5xl:grid-cols-[minmax(0,1fr)_22rem] @5xl:grid-rows-[auto_1fr] gap-4 items-start">
                <div className="min-w-0 order-1 @5xl:col-start-1 @5xl:row-start-1">
                    <ScannerStatusStrip scannerId={scannerId} />
                </div>
                {/* Its own column when wide. When stacked it dissolves, so the digest follows the status and self-driving drops below the findings. */}
                <div className="contents @5xl:flex @5xl:flex-col @5xl:gap-4 @5xl:col-start-2 @5xl:row-start-1 @5xl:row-span-2">
                    <div className="min-w-0 order-2">
                        <ScannerScoutCard scannerId={scannerId} scannerName={scanner.name || ''} />
                    </div>
                    <div className="min-w-0 order-5 @5xl:order-3">
                        <ScannerSetupCard scannerId={scannerId} />
                    </div>
                    <div className="min-w-0 order-4">
                        <ScannerSelfDrivingCard scannerId={scannerId} />
                    </div>
                </div>
                <div className="@container min-w-0 flex flex-col gap-4 order-3 @5xl:col-start-1 @5xl:row-start-2">
                    {firstScanPending ? (
                        <FirstScanPendingPanel scannerId={scannerId} />
                    ) : (
                        <div className="border rounded bg-surface-primary p-4 flex flex-col gap-4">
                            <div className="flex flex-wrap items-start justify-between gap-x-4 gap-y-2 border-b pb-3">
                                <div>
                                    <div className="text-sm font-medium">Findings</div>
                                    <FindingsCoverage scannerId={scannerId} />
                                </div>
                                <ScannerOverviewFilters scannerId={scannerId} />
                            </div>
                            {body}
                        </div>
                    )}
                </div>
            </div>
        </div>
    )
}
