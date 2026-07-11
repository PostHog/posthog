import { useActions, useValues } from 'kea'
import { useCallback, useEffect, useMemo, useState } from 'react'

import {
    IconChevronDown,
    IconChevronRight,
    IconExpand45,
    IconRefresh,
    IconRewindPlay,
    IconSparkles,
} from '@posthog/icons'
import {
    LemonButton,
    LemonInput,
    LemonModal,
    LemonSegmentedButton,
    LemonTable,
    LemonTag,
    LemonTagType,
    Link,
    Spinner,
    Tooltip,
} from '@posthog/lemon-ui'
import { BarChart, useChartLayout } from '@posthog/quill-charts'

import { buildTheme } from 'lib/charts/utils/theme'
import { getColorVar } from 'lib/colors'
import MonacoDiffEditor from 'lib/components/MonacoDiffEditor'
import { TZLabel } from 'lib/components/TZLabel'
import { dayjs } from 'lib/dayjs'
import { LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { getAccessControlDisabledReason } from 'lib/utils/accessControlUtils'
import { urls } from 'scenes/urls'

import { themeLogic } from '~/layout/navigation-3000/themeLogic'
import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { ObservationResultSummary } from '../../components/ObservationCard'
import type { ReplayObservationApi, ReplayScannerPromptSuggestionApi } from '../../generated/api.schemas'
import { visionQuotaLogic } from '../../logics/visionQuotaLogic'
import { ObservationLabelControl, ObservationLabelFeedback } from '../../observations/ObservationLabelControl'
import { formatCredits } from '../../utils/credits'
import { fillLabelDays, versionAccuracyStrip } from '../../utils/labelStats'
import { readConfidence } from '../../utils/observation'
import { replayScannerLogic } from '../replayScannerLogic'
import { ReplayScannerTab, replayScannerSceneLogic } from '../replayScannerSceneLogic'
import { LABEL_CHART_DAYS, QUALITY_PAGE_SIZE, RatedFilterValue, scannerQualityLogic } from '../scannerQualityLogic'
import { OBSERVATION_CREDITS_BY_MODEL } from '../types'
import { versionTag } from './ScannerObservationsTable'

const RATED_FILTER_OPTIONS: { value: RatedFilterValue; label: string }[] = [
    { value: 'unrated', label: 'Unrated' },
    { value: 'rated', label: 'Rated' },
    { value: 'all', label: 'All' },
]

const SUGGESTION_STATUS_TAGS: Record<string, { type: LemonTagType; label: string; tooltip: string }> = {
    applied: {
        type: 'success',
        label: 'Applied',
        tooltip: 'This prompt was applied to the scanner as a new version',
    },
    dismissed: {
        type: 'muted',
        label: 'Dismissed',
        tooltip: 'This recommendation was rejected without being applied',
    },
    superseded: {
        type: 'muted',
        label: 'Superseded',
        tooltip: 'A newer recommendation replaced this one before it was applied',
    },
    no_change: {
        type: 'success',
        label: 'Looks good',
        tooltip: 'The prompt already handles the rated sessions well; nothing to change',
    },
}

function SuggestionStatusTag({ status }: { status: string }): JSX.Element | null {
    const tag = SUGGESTION_STATUS_TAGS[status]
    if (!tag) {
        return null
    }
    return (
        <Tooltip title={tag.tooltip}>
            <LemonTag type={tag.type}>{tag.label}</LemonTag>
        </Tooltip>
    )
}

/** The bordered side-by-side diff with labeled panes, rendered inline and inside the fullscreen modal. */
function SuggestionDiffPanes({
    suggestion,
    beforeLabel,
    isDarkModeOn,
    editorHeight,
    onExpand,
}: {
    suggestion: ReplayScannerPromptSuggestionApi
    beforeLabel: string
    isDarkModeOn: boolean
    editorHeight?: string
    onExpand?: () => void
}): JSX.Element {
    return (
        <div className="border rounded overflow-hidden">
            <div className="flex items-center border-b bg-surface-secondary text-xs font-medium">
                <div className="flex-1 px-3 py-1.5 border-r">{beforeLabel}</div>
                <div className="flex-1 px-3 py-1.5 flex items-center justify-between">
                    <span>Suggested prompt</span>
                    {onExpand && (
                        <LemonButton
                            size="xsmall"
                            icon={<IconExpand45 />}
                            tooltip="Expand diff to full screen"
                            onClick={onExpand}
                            data-attr="vision-quality-expand-diff"
                        />
                    )}
                </div>
            </div>
            <MonacoDiffEditor
                original={suggestion.base_prompt}
                modified={suggestion.suggested_prompt}
                language="markdown"
                theme={isDarkModeOn ? 'vs-dark' : 'vs-light'}
                height={editorHeight}
                options={{
                    readOnly: true,
                    renderSideBySide: true,
                    useInlineViewWhenSpaceIsLimited: false,
                    // Keep both panes at exactly half width on resize, in lockstep with the header row.
                    enableSplitViewResizing: false,
                    splitViewDefaultRatio: 0.5,
                    automaticLayout: true,
                    wordWrap: 'on',
                    lineNumbers: 'off',
                    folding: false,
                    renderOverviewRuler: false,
                    scrollBeyondLastLine: false,
                    diffAlgorithm: 'advanced',
                }}
            />
        </div>
    )
}

/** The pane-labeled prompt diff plus the model's rationale, shared by the current card and history entries. */
function SuggestionDetails({
    suggestion,
    beforeLabel,
    isDarkModeOn,
}: {
    suggestion: ReplayScannerPromptSuggestionApi
    beforeLabel: string
    isDarkModeOn: boolean
}): JSX.Element {
    const [isDiffExpanded, setIsDiffExpanded] = useState(false)
    return (
        <>
            {suggestion.base_prompt ? (
                <>
                    <SuggestionDiffPanes
                        suggestion={suggestion}
                        beforeLabel={beforeLabel}
                        isDarkModeOn={isDarkModeOn}
                        onExpand={() => setIsDiffExpanded(true)}
                    />
                    <LemonModal
                        isOpen={isDiffExpanded}
                        onClose={() => setIsDiffExpanded(false)}
                        title="Prompt recommendation"
                        fullScreen
                    >
                        <div className="space-y-4">
                            <SuggestionDiffPanes
                                suggestion={suggestion}
                                beforeLabel={beforeLabel}
                                isDarkModeOn={isDarkModeOn}
                                editorHeight="calc(100vh - 16rem)"
                            />
                            {suggestion.rationale && (
                                <div>
                                    <h4 className="text-sm font-semibold m-0 mb-1">Why</h4>
                                    <p className="text-sm text-muted m-0">{suggestion.rationale}</p>
                                </div>
                            )}
                        </div>
                    </LemonModal>
                </>
            ) : (
                <div className="border rounded bg-surface-secondary p-2 font-mono text-xs whitespace-pre-wrap max-h-48 overflow-y-auto">
                    {suggestion.suggested_prompt}
                </div>
            )}
            {suggestion.rationale && (
                <div>
                    <h4 className="text-sm font-semibold m-0 mb-1">Why</h4>
                    <p className="text-sm text-muted m-0">{suggestion.rationale}</p>
                </div>
            )}
        </>
    )
}

function SuggestionMeta({ suggestion }: { suggestion: ReplayScannerPromptSuggestionApi }): JSX.Element {
    return (
        <span className="text-xs text-muted">
            Based on {suggestion.based_on_up} thumbs up · {suggestion.based_on_down} thumbs down · generated{' '}
            <TZLabel time={suggestion.created_at} className="align-baseline" /> against v{suggestion.scanner_version}
        </span>
    )
}

const EVALUATION_OUTCOME_TAGS: Record<string, { type: LemonTagType; label: string }> = {
    kept: { type: 'success', label: 'Kept' },
    fixed: { type: 'success', label: 'Fixed' },
    regressed: { type: 'danger', label: 'Regressed' },
    still_wrong: { type: 'danger', label: 'Still wrong' },
    error: { type: 'muted', label: 'Error' },
}

/** Test-before-apply results: the suggested prompt re-run against rated sessions. */
function SuggestionEvaluationPanel({
    suggestion,
}: {
    suggestion: ReplayScannerPromptSuggestionApi
}): JSX.Element | null {
    const [detailsOpen, setDetailsOpen] = useState(false)
    const evaluation = suggestion.evaluation
    if (!evaluation) {
        return null
    }

    if (evaluation.status === 'running') {
        return (
            <div className="border rounded p-3 flex items-center gap-2 text-sm text-muted">
                <Spinner />
                Testing against rated sessions… {evaluation.results.length} of {evaluation.total || '?'} done
            </div>
        )
    }

    if (evaluation.status === 'failed' && !evaluation.results.length) {
        return (
            <div className="border rounded p-3 text-sm text-muted">
                The test didn't finish. Run it again to check this prompt against your rated sessions.
            </div>
        )
    }

    const summary = evaluation.summary ?? { kept: 0, regressed: 0, fixed: 0, still_wrong: 0, errors: 0 }
    const downTotal = summary.fixed + summary.still_wrong
    const upTotal = summary.kept + summary.regressed
    // Only sessions that ran successfully were charged.
    const chargedCount = evaluation.results.filter((result) => result.outcome !== 'error').length
    return (
        <div className="border rounded p-3 space-y-2">
            <div className="flex flex-wrap items-center gap-2 text-sm">
                <span className="font-medium">Tested against {evaluation.results.length} rated sessions:</span>
                {downTotal > 0 && (
                    <Tooltip title="Rated-wrong sessions whose result changed under the suggested prompt">
                        <LemonTag type={summary.fixed > 0 ? 'success' : 'muted'}>
                            {summary.fixed}/{downTotal} wrong now different
                        </LemonTag>
                    </Tooltip>
                )}
                {upTotal > 0 && (
                    <Tooltip title="Rated-right sessions whose result is unchanged under the suggested prompt">
                        <LemonTag type={summary.regressed > 0 ? 'danger' : 'success'}>
                            {summary.kept}/{upTotal} right unchanged
                        </LemonTag>
                    </Tooltip>
                )}
                {summary.errors > 0 && <LemonTag type="muted">{summary.errors} failed to run</LemonTag>}
                <Tooltip title="Only sessions that ran successfully count against the monthly Replay Vision quota">
                    <span className="text-muted text-xs">
                        Used {chargedCount} observation{chargedCount === 1 ? '' : 's'} of quota
                    </span>
                </Tooltip>
            </div>
            <LemonButton
                size="xsmall"
                type="tertiary"
                icon={detailsOpen ? <IconChevronDown /> : <IconChevronRight />}
                onClick={() => setDetailsOpen(!detailsOpen)}
                data-attr="vision-quality-evaluation-details-toggle"
            >
                Per-session results
            </LemonButton>
            {detailsOpen && (
                <div className="space-y-1">
                    {evaluation.results.map((result) => (
                        <div key={result.session_id} className="flex flex-wrap items-center gap-2 text-xs">
                            <LemonTag type={EVALUATION_OUTCOME_TAGS[result.outcome]?.type ?? 'muted'}>
                                {EVALUATION_OUTCOME_TAGS[result.outcome]?.label ?? result.outcome}
                            </LemonTag>
                            <Link to={urls.replaySingle(result.session_id)} className="font-mono">
                                {result.session_id.slice(0, 8)}…
                            </Link>
                            <span className="text-muted">
                                rated {result.rated_correct ? 'right' : 'wrong'} · {result.before ?? 'n/a'} →{' '}
                                {result.after ?? (result.error ? `failed: ${result.error.slice(0, 80)}` : 'n/a')}
                            </span>
                        </div>
                    ))}
                </div>
            )}
        </div>
    )
}

function PromptRecommendationPanel({ scannerId }: { scannerId: string }): JSX.Element {
    const logic = scannerQualityLogic({ scannerId })
    const {
        currentSuggestion,
        suggestionStale,
        ratedCount,
        evaluationSessionCap,
        plannedTestSessions,
        suggestionLoading,
        generating,
        applying,
        dismissing,
        evaluating,
        suggestionHistory,
        suggestionHistoryLoading,
    } = useValues(logic)
    const {
        generateSuggestion,
        applySuggestion,
        dismissSuggestion,
        evaluateSuggestion,
        setTestSessionLimit,
        loadSuggestionHistory,
    } = useActions(logic)
    const { scanner } = useValues(replayScannerLogic({ id: scannerId }))
    const { quota } = useValues(visionQuotaLogic)
    const { isDarkModeOn } = useValues(themeLogic)
    // Only scanner types with a discrete outcome (verdict, tags) can be diffed against ratings.
    const evaluationSupported = scanner?.scanner_type === 'monitor' || scanner?.scanner_type === 'classifier'
    // Each re-run is charged like a normal observation of the scanner's model.
    const creditsPerTestSession = scanner ? (OBSERVATION_CREDITS_BY_MODEL[scanner.model] ?? 0) : 0
    const plannedTestCredits = plannedTestSessions * creditsPerTestSession
    const [historyOpen, setHistoryOpen] = useState(false)
    const editDisabledReason = getAccessControlDisabledReason(
        AccessControlResourceType.SessionRecording,
        AccessControlLevel.Editor
    )

    const pastSuggestions = suggestionHistory.filter((s) => s.id !== currentSuggestion?.id)

    let body: JSX.Element
    if (suggestionLoading && !currentSuggestion) {
        body = (
            <div className="flex items-center justify-center py-6 text-muted">
                <Spinner />
            </div>
        )
    } else if (!currentSuggestion && generating) {
        body = (
            <div className="flex items-center gap-2 py-4 text-muted text-sm">
                <Spinner /> Generating a recommendation from your team's ratings…
            </div>
        )
    } else if (!currentSuggestion) {
        body = (
            <div className="flex flex-wrap items-center justify-between gap-2 py-2">
                <span className="text-muted text-sm">
                    {ratedCount === 0
                        ? 'Rate results below and PostHog AI will recommend prompt improvements here.'
                        : 'No recommendation yet for the current ratings.'}
                </span>
                <LemonButton
                    size="small"
                    type="secondary"
                    icon={<IconSparkles />}
                    loading={generating}
                    disabledReason={
                        editDisabledReason ?? (ratedCount === 0 ? 'Rate at least one result first' : undefined)
                    }
                    onClick={() => generateSuggestion()}
                    data-attr="vision-quality-generate-suggestion"
                >
                    Generate recommendation
                </LemonButton>
            </div>
        )
    } else if (currentSuggestion.status === 'no_change') {
        body = (
            <div className="space-y-3">
                <p className="text-sm m-0">
                    Your scanner configuration looks good! PostHog AI reviewed the rated sessions and has no prompt
                    changes to recommend.
                </p>
                {currentSuggestion.rationale && <p className="text-sm text-muted m-0">{currentSuggestion.rationale}</p>}
                <SuggestionMeta suggestion={currentSuggestion} />
            </div>
        )
    } else {
        body = (
            <div className="space-y-3">
                <SuggestionDetails
                    suggestion={currentSuggestion}
                    beforeLabel={`Current prompt (v${currentSuggestion.scanner_version})`}
                    isDarkModeOn={isDarkModeOn}
                />
                {currentSuggestion.status === 'pending' && <SuggestionEvaluationPanel suggestion={currentSuggestion} />}
                <div className="flex flex-wrap items-center justify-between gap-2">
                    <SuggestionMeta suggestion={currentSuggestion} />
                    <div className="flex items-center gap-2">
                        {currentSuggestion.status === 'pending' && evaluationSupported && (
                            <LemonButton
                                size="small"
                                type="secondary"
                                loading={evaluating || currentSuggestion.evaluation?.status === 'running'}
                                disabledReason={
                                    editDisabledReason ??
                                    (ratedCount === 0
                                        ? 'Rate at least one result first'
                                        : quota?.exhausted && quota.credit_limit !== null
                                          ? `Monthly Replay Vision budget of ${formatCredits(quota.credit_limit)} reached. Resets ${dayjs(quota.period_end).format('MMM D')}.`
                                          : quota && quota.remaining !== null && plannedTestCredits > quota.remaining
                                            ? `Only ${formatCredits(quota.remaining)} of budget left this month. Lower the test session count.`
                                            : undefined)
                                }
                                tooltip="Re-runs the scanner with the suggested prompt against your rated sessions, so you can see what would change before applying. Each tested session is charged like a normal observation. Pick how many below."
                                onClick={() => evaluateSuggestion(currentSuggestion.id)}
                                data-attr="vision-quality-evaluate-suggestion"
                            >
                                {currentSuggestion.evaluation ? 'Re-test' : 'Test against rated sessions'}
                            </LemonButton>
                        )}
                        {currentSuggestion.status === 'pending' && (
                            <LemonButton
                                size="small"
                                type="tertiary"
                                loading={dismissing}
                                disabledReason={editDisabledReason ?? undefined}
                                onClick={() => dismissSuggestion(currentSuggestion.id)}
                                data-attr="vision-quality-dismiss-suggestion"
                            >
                                Dismiss
                            </LemonButton>
                        )}
                        {currentSuggestion.status === 'pending' && (
                            <LemonButton
                                size="small"
                                type="primary"
                                loading={applying}
                                disabledReason={editDisabledReason ?? undefined}
                                tooltip="Writes this prompt to the scanner as a new version"
                                onClick={() => applySuggestion(currentSuggestion.id)}
                                data-attr="vision-quality-apply-suggestion"
                            >
                                Apply to scanner
                            </LemonButton>
                        )}
                    </div>
                </div>
                {currentSuggestion.status === 'pending' && evaluationSupported && plannedTestSessions > 0 && (
                    <div className="flex items-center justify-end gap-1.5 text-xs text-muted">
                        <span>Testing re-runs</span>
                        <LemonInput
                            type="number"
                            size="xsmall"
                            min={1}
                            max={Math.min(evaluationSessionCap, ratedCount)}
                            value={plannedTestSessions}
                            onChange={(value) => setTestSessionLimit(value ?? null)}
                            className="w-14"
                            data-attr="vision-quality-test-session-limit"
                        />
                        <span>
                            of your {Math.min(evaluationSessionCap, ratedCount)} most useful rated session
                            {Math.min(evaluationSessionCap, ratedCount) === 1 ? '' : 's'}, charging{' '}
                            {formatCredits(plannedTestCredits)}
                            {quota && quota.remaining !== null && quota.credit_limit !== null
                                ? ` (${formatCredits(quota.remaining)} of ${formatCredits(quota.credit_limit)} left this month)`
                                : ''}
                            .
                        </span>
                    </div>
                )}
            </div>
        )
    }

    return (
        <div className="border rounded p-4 bg-surface-primary space-y-4">
            <div className="flex flex-wrap items-center gap-2">
                <span className="text-sm font-medium">Prompt recommendation</span>
                {currentSuggestion && <SuggestionStatusTag status={currentSuggestion.status} />}
                {suggestionStale && currentSuggestion && (
                    <Tooltip title="Refreshes automatically about once a day; regenerate to update now">
                        <LemonTag type="warning">New ratings since this was generated</LemonTag>
                    </Tooltip>
                )}
                <div className="ml-auto flex items-center gap-2">
                    {currentSuggestion && (
                        <LemonButton
                            size="xsmall"
                            type="secondary"
                            icon={<IconRefresh />}
                            loading={generating}
                            disabledReason={
                                editDisabledReason ?? (ratedCount === 0 ? 'Rate at least one result first' : undefined)
                            }
                            onClick={() => generateSuggestion()}
                            data-attr="vision-quality-regenerate-suggestion"
                        >
                            Regenerate
                        </LemonButton>
                    )}
                </div>
            </div>
            {body}
            <div className="border-t pt-3">
                <LemonButton
                    size="xsmall"
                    type="tertiary"
                    icon={historyOpen ? <IconChevronDown /> : <IconChevronRight />}
                    onClick={() => {
                        const next = !historyOpen
                        setHistoryOpen(next)
                        // Refetch on every open: generate/apply/dismiss change history server-side.
                        if (next) {
                            loadSuggestionHistory()
                        }
                    }}
                    data-attr="vision-quality-suggestion-history-toggle"
                >
                    Past recommendations
                </LemonButton>
                {historyOpen &&
                    (suggestionHistoryLoading ? (
                        <div className="flex items-center justify-center py-3 text-muted">
                            <Spinner />
                        </div>
                    ) : pastSuggestions.length === 0 ? (
                        <div className="text-muted text-xs py-2">No past recommendations yet.</div>
                    ) : (
                        <div className="space-y-2 pt-2">
                            {pastSuggestions.map((suggestion) => {
                                return (
                                    <div key={suggestion.id} className="border rounded p-3 space-y-3">
                                        <div className="flex flex-wrap items-center gap-2">
                                            <SuggestionStatusTag status={suggestion.status} />
                                            <SuggestionMeta suggestion={suggestion} />
                                        </div>
                                        <SuggestionDetails
                                            suggestion={suggestion}
                                            beforeLabel={`Prompt then (v${suggestion.scanner_version})`}
                                            isDarkModeOn={isDarkModeOn}
                                        />
                                    </div>
                                )
                            })}
                        </div>
                    ))}
            </div>
        </div>
    )
}

interface VersionBadgePosition {
    version: number
    label: string
    prompt: string
    x: number
}

/** Reads band-center pixels from the chart context and reports them up: the chart shell clips
 *  overlays (overflow-hidden), so the badges themselves render as a sibling row below the chart. */
function VersionBadgeBridge({
    markers,
    onPositions,
}: {
    markers: Omit<VersionBadgePosition, 'x'>[]
    onPositions: (positions: VersionBadgePosition[]) => void
}): null {
    const { scales } = useChartLayout()
    useEffect(() => {
        onPositions(
            markers.flatMap((marker) => {
                const x = scales.x(marker.label)
                return x !== undefined && isFinite(x) ? [{ ...marker, x }] : []
            })
        )
    }, [markers, scales, onPositions])
    return null
}

type ChartMode = 'session' | 'rating'

// Full "MMM D" labels collide at 30 days and the chart drops the overlap, hiding dates.
// Keep the month only where it anchors (first tick, month boundaries) so every day fits.
function formatChartDay(label: string, index: number): string {
    const day = label.split(' ')[1]
    return index === 0 || day === '1' ? label : day
}

const CHART_MODE_OPTIONS: { value: ChartMode; label: string; tooltip: string }[] = [
    {
        value: 'session',
        label: 'By session day',
        tooltip: 'Ratings placed on the day the session was scanned: how scanner quality trends over time',
    },
    {
        value: 'rating',
        label: 'By rating day',
        tooltip: "Ratings placed on the day they were given or changed: the team's rating activity",
    },
]

function RatingsOverTimePanel({ scannerId }: { scannerId: string }): JSX.Element {
    const { labelStats, labelStatsLoading } = useValues(scannerQualityLogic({ scannerId }))
    const { scanner } = useValues(replayScannerLogic({ id: scannerId }))
    const { setActiveTab } = useActions(replayScannerSceneLogic)
    const { isDarkModeOn } = useValues(themeLogic)
    // buildTheme snapshots the current CSS vars, so rebuild when the app theme flips.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    const theme = useMemo(() => buildTheme(), [isDarkModeOn])
    const [mode, setMode] = useState<ChartMode>('session')
    const [badgePositions, setBadgePositionsRaw] = useState<VersionBadgePosition[]>([])
    // Bail on identical positions so the measure->report->render loop settles instead of cycling.
    const setBadgePositions = useCallback((next: VersionBadgePosition[]) => {
        setBadgePositionsRaw((prev) => (JSON.stringify(prev) === JSON.stringify(next) ? prev : next))
    }, [])
    const chart = useMemo(
        () =>
            labelStats
                ? fillLabelDays(mode === 'session' ? labelStats.by_day : labelStats.by_rating_day, LABEL_CHART_DAYS)
                : null,
        [labelStats, mode]
    )
    // Prompt-version markers sit on calendar time, so they render under the dates in both views.
    const versionMarkers = useMemo(
        () =>
            labelStats && chart
                ? labelStats.version_markers
                      // Markers are all-time but the chart is windowed, so match full dates:
                      // last year's "Jul 7" must not land on today's bar.
                      .filter((marker) => chart.dates.includes(marker.date))
                      .map((marker) => ({
                          version: marker.version,
                          label: dayjs(marker.date).format('MMM D'),
                          prompt: marker.prompt,
                      }))
                : [],
        [labelStats, chart]
    )
    const totalRated = (labelStats?.up_total ?? 0) + (labelStats?.down_total ?? 0)
    // Thumbs-up share per prompt version, from rated sessions only. The active version stays
    // visible while unrated or unscanned, so a fresh prompt never implies the old one is live.
    const versionAccuracy = useMemo(
        () => versionAccuracyStrip(labelStats?.version_markers ?? [], scanner?.scanner_version),
        [labelStats, scanner]
    )

    return (
        <div className="border rounded p-4 bg-surface-primary space-y-3">
            <div className="flex flex-wrap items-center gap-2">
                <span className="text-sm font-medium">Ratings over time</span>
                <span className="text-xs text-muted tabular-nums">
                    {totalRated > 0
                        ? `${labelStats?.up_total ?? 0} thumbs up · ${labelStats?.down_total ?? 0} thumbs down`
                        : `last ${LABEL_CHART_DAYS} days`}
                </span>
                <div className="ml-auto">
                    <LemonSegmentedButton
                        size="xsmall"
                        value={mode}
                        onChange={setMode}
                        options={CHART_MODE_OPTIONS}
                        data-attr="vision-quality-chart-mode"
                    />
                </div>
            </div>
            {versionAccuracy.length > 0 && (
                <div className="flex flex-wrap items-center gap-1.5 text-xs tabular-nums">
                    {versionAccuracy.map((entry) => (
                        <Tooltip
                            key={entry.version}
                            title={
                                entry.pct !== null
                                    ? `${entry.rated} rated of ${entry.scanned} scanned on v${entry.version}. Unrated sessions don't count toward the percentage.`
                                    : entry.scanned > 0
                                      ? `v${entry.version} has scanned ${entry.scanned} sessions but none are rated yet. Rate results below to compare it with earlier versions.`
                                      : "This prompt version was applied but hasn't scanned any sessions yet, so it has no ratings or chart marker"
                            }
                        >
                            <LemonTag type={entry.isCurrent ? 'highlight' : 'muted'}>
                                {entry.pct !== null
                                    ? `v${entry.version} · ${entry.pct}% thumbs up (${entry.rated})`
                                    : entry.scanned > 0
                                      ? `v${entry.version} · no ratings yet`
                                      : `v${entry.version} · no scans yet`}
                            </LemonTag>
                        </Tooltip>
                    ))}
                </div>
            )}
            {labelStatsLoading && !labelStats ? (
                <div className="flex items-center justify-center py-6 text-muted">
                    <Spinner />
                </div>
            ) : totalRated === 0 || !chart ? (
                <div className="text-muted text-sm">
                    No rated sessions yet. Rate results below to start tracking scanner quality. As the prompt improves,
                    thumbs down should trend down.
                </div>
            ) : (
                <>
                    <div className="h-48 flex flex-col">
                        <BarChart
                            labels={chart.labels}
                            series={[
                                { key: 'up', label: 'Thumbs up', color: getColorVar('success'), data: chart.up },
                                { key: 'down', label: 'Thumbs down', color: getColorVar('danger'), data: chart.down },
                            ]}
                            config={{ showGrid: false, barLayout: 'stacked', xTickFormatter: formatChartDay }}
                            theme={theme}
                        >
                            <VersionBadgeBridge markers={versionMarkers} onPositions={setBadgePositions} />
                        </BarChart>
                    </div>
                    {badgePositions.length > 0 && (
                        <div className="relative h-5">
                            {badgePositions.map((badge) => (
                                <Tooltip
                                    key={badge.version}
                                    title={
                                        <div className="space-y-1 max-w-100">
                                            <div className="font-semibold">
                                                Prompt v{badge.version} · active from {badge.label}
                                            </div>
                                            {badge.prompt && (
                                                <div className="font-mono text-xs whitespace-pre-wrap">
                                                    {badge.prompt.length > 280
                                                        ? `${badge.prompt.slice(0, 280)}…`
                                                        : badge.prompt}
                                                </div>
                                            )}
                                            <div className="text-muted">Click to view all prompt versions</div>
                                        </div>
                                    }
                                >
                                    <div
                                        className="absolute top-0 -translate-x-1/2 inline-flex cursor-pointer items-center justify-center rounded border bg-surface-secondary px-1.5 py-0.5 text-[10px] font-mono leading-none text-muted hover:text-default"
                                        style={{ left: badge.x }}
                                        onClick={() => setActiveTab(ReplayScannerTab.Configuration)}
                                        data-attr="vision-quality-version-badge"
                                    >
                                        v{badge.version}
                                    </div>
                                </Tooltip>
                            ))}
                        </div>
                    )}
                </>
            )}
        </div>
    )
}

/**
 * The scanner's Quality tab: the current prompt recommendation (with history), quality over time,
 * and the results still awaiting a rating.
 */
export function ScannerQualityTab({ scannerId }: { scannerId: string }): JSX.Element {
    const logic = scannerQualityLogic({ scannerId })
    const { observations, observationsLoading, total, page, ratedFilter, sort } = useValues(logic)
    const { setPage, setRatedFilter, setSort, labelChanged } = useActions(logic)
    const { scanner } = useValues(replayScannerLogic({ id: scannerId }))
    const scannerType = scanner?.scanner_type

    const columns: LemonTableColumns<ReplayObservationApi> = [
        {
            title: 'Session',
            key: 'session',
            width: 260,
            render: (_, obs) => (
                <Link
                    to={urls.replayVisionObservation(obs.id)}
                    className="font-mono text-xs text-primary truncate block"
                >
                    {obs.session_id}
                </Link>
            ),
        },
        {
            title: 'Result',
            key: 'result',
            render: (_, obs) => (
                <Link to={urls.replayVisionObservation(obs.id)} className="block">
                    <div className="min-w-[16rem] max-w-xl">
                        <ObservationResultSummary observation={obs} />
                    </div>
                </Link>
            ),
            sorter: scannerType === 'scorer' || scannerType === 'monitor' ? true : undefined,
        },
        {
            title: 'Confidence',
            key: 'confidence',
            width: 110,
            tooltip:
                'How sure the scanner was of this result. Rating low-confidence sessions first teaches the prompt the most.',
            render: (_, obs) => {
                const confidence = readConfidence(obs)
                if (confidence === null) {
                    return <span className="text-muted">—</span>
                }
                return <span className="tabular-nums">{Math.round(confidence * 100)}%</span>
            },
            sorter: true,
        },
        {
            title: 'Scanner got it right?',
            key: 'rating',
            width: 160,
            render: (_, obs) => (
                <ObservationLabelControl
                    compact
                    observationId={obs.id}
                    initialLabel={obs.label}
                    onChange={(label) => labelChanged(obs.id, label)}
                />
            ),
        },
        {
            title: 'Feedback',
            key: 'feedback',
            width: 320,
            render: (_, obs) => (
                <ObservationLabelFeedback
                    observationId={obs.id}
                    initialLabel={obs.label}
                    onChange={(label) => labelChanged(obs.id, label)}
                />
            ),
        },
        {
            title: 'Version',
            key: 'version',
            render: (_, obs) => {
                const tag = versionTag(obs.scanner_snapshot?.scanner_version, scanner?.scanner_version)
                if (!tag) {
                    return <span className="text-muted">—</span>
                }
                return (
                    <Tooltip title={tag.tooltip}>
                        <LemonTag type={tag.type} className="font-mono">
                            {tag.label}
                        </LemonTag>
                    </Tooltip>
                )
            },
            sorter: true,
        },
        {
            title: 'Created',
            key: 'created_at',
            render: (_, obs) => <TZLabel time={obs.created_at} />,
            sorter: true,
        },
        {
            title: '',
            key: 'actions',
            width: 1,
            render: (_, obs) => (
                <LemonButton
                    size="small"
                    type="secondary"
                    icon={<IconRewindPlay />}
                    to={urls.replaySingle(obs.session_id)}
                    className="whitespace-nowrap"
                    data-attr="vision-quality-view-recording"
                >
                    View recording
                </LemonButton>
            ),
        },
    ]

    return (
        <div className="flex flex-col gap-6">
            <p className="text-muted m-0 max-w-2xl">
                Rate scanner results with a thumbs up or down, and optionally add feedback explaining why. PostHog AI
                turns your team's ratings into the prompt recommendation below.
            </p>

            <PromptRecommendationPanel scannerId={scannerId} />

            <RatingsOverTimePanel scannerId={scannerId} />

            <div className="space-y-3">
                <div className="flex items-start gap-3">
                    <div>
                        <h3 className="font-semibold text-base m-0">Rate results</h3>
                        <p className="text-muted text-xs m-0 mt-0.5">
                            The more results your team rates, and the more feedback you leave, the better the prompt
                            recommendations get.
                        </p>
                    </div>
                    <div className="ml-auto">
                        <LemonSegmentedButton
                            size="small"
                            value={ratedFilter}
                            onChange={setRatedFilter}
                            options={RATED_FILTER_OPTIONS}
                            data-attr="vision-quality-rated-filter"
                        />
                    </div>
                </div>
                <LemonTable
                    columns={columns}
                    dataSource={observations}
                    loading={observationsLoading}
                    rowKey="id"
                    pagination={{
                        controlled: true,
                        pageSize: QUALITY_PAGE_SIZE,
                        currentPage: page,
                        entryCount: total,
                        onForward: () => setPage(page + 1),
                        onBackward: () => setPage(page - 1),
                    }}
                    sorting={sort}
                    onSort={(next) => setSort(next)}
                    useURLForSorting={false}
                    nouns={['observation', 'observations']}
                    emptyState={
                        <div className="p-6 text-center text-muted">
                            {ratedFilter === 'rated'
                                ? 'No rated observations yet. Rate some under "All" or "Unrated".'
                                : ratedFilter === 'unrated'
                                  ? 'No unrated observations. Everything has been rated.'
                                  : "No successful observations to rate yet. They'll appear here once the scanner produces results."}
                        </div>
                    }
                />
            </div>
        </div>
    )
}
