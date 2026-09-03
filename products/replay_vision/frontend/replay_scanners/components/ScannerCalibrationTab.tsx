import { useActions, useValues } from 'kea'
import { useCallback, useEffect, useMemo, useState } from 'react'

import { IconChevronDown, IconChevronRight, IconRefresh, IconRewindPlay, IconSparkles } from '@posthog/icons'
import {
    LemonButton,
    LemonInput,
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
import { TZLabel } from 'lib/components/TZLabel'
import { dayjs } from 'lib/dayjs'
import { LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { sessionPlayerModalLogic } from 'scenes/session-recordings/player/modal/sessionPlayerModalLogic'
import { urls } from 'scenes/urls'

import { themeLogic } from '~/layout/navigation-3000/themeLogic'

import { VisionDocsLink } from '../../components/DocsLink'
import { ObservationResultSummary } from '../../components/ObservationCard'
import type {
    FeedbackThemesApi,
    PromptEvaluationResultApi,
    ReplayObservationApi,
    ReplayScannerPromptSuggestionApi,
} from '../../generated/api.schemas'
import { visionQuotaLogic } from '../../logics/visionQuotaLogic'
import { ObservationLabelControl, ObservationLabelFeedback } from '../../observations/ObservationLabelControl'
import { getReplayVisionEditDisabledReason } from '../../utils/accessControl'
import { formatCreditCount, formatCreditsRange } from '../../utils/credits'
import { buildChartDayFormatter, fillLabelDays, versionAccuracyStrip } from '../../utils/labelStats'
import { readConfidence } from '../../utils/observation'
import { replayScannerLogic } from '../replayScannerLogic'
import { ReplayScannerTab, replayScannerSceneLogic } from '../replayScannerSceneLogic'
import {
    LABEL_CHART_DAYS,
    CALIBRATION_PAGE_SIZE,
    RatedFilterValue,
    scannerCalibrationLogic,
} from '../scannerCalibrationLogic'
import { OBSERVATION_CREDITS_BY_MODEL } from '../types'
import { ConfigChangeCards } from './ConfigChangeCards'
import { versionTag } from './ScannerObservationsTable'

// data-attr must live on each option: LemonSegmentedButton renders no element of its own that takes one.
const RATED_FILTER_OPTIONS: { value: RatedFilterValue; label: string; 'data-attr': string }[] = [
    { value: 'unrated', label: 'Unrated', 'data-attr': 'vision-calibration-rated-filter-unrated' },
    { value: 'rated', label: 'Rated', 'data-attr': 'vision-calibration-rated-filter-rated' },
    { value: 'all', label: 'All', 'data-attr': 'vision-calibration-rated-filter-all' },
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
        label: 'No changes needed',
        tooltip: 'The prompt already handles the rated results well, so there is nothing to change',
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

/** The change cards plus the model's rationale, shared by the current card and history entries. History
 *  entries render read-only; the current card is editable per field. */
function SuggestionDetails({
    suggestion,
    isDarkModeOn,
    scannerId,
    readOnly = false,
}: {
    suggestion: ReplayScannerPromptSuggestionApi
    isDarkModeOn: boolean
    scannerId: string
    readOnly?: boolean
}): JSX.Element {
    return (
        <>
            <ConfigChangeCards
                suggestion={suggestion}
                isDarkModeOn={isDarkModeOn}
                scannerId={scannerId}
                readOnly={readOnly}
            />
            {suggestion.rationale && (
                <div>
                    <h4 className="text-sm font-semibold m-0 mb-1">Why this change</h4>
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
    preview: { type: 'muted', label: 'Preview' },
}

/** Test-before-apply results: the suggested prompt re-run against rated sessions. */
function SuggestionEvaluationPanel({
    suggestion,
    preview,
    editedSinceTest,
}: {
    suggestion: ReplayScannerPromptSuggestionApi
    preview: boolean
    editedSinceTest: boolean
}): JSX.Element | null {
    const [detailsOpen, setDetailsOpen] = useState(false)
    const { openSessionPlayer } = useActions(sessionPlayerModalLogic)
    const evaluation = suggestion.evaluation
    if (!evaluation) {
        return null
    }
    const isPreview = preview || evaluation.results.some((result) => result.outcome === 'preview')

    if (evaluation.status === 'running') {
        return (
            <div className="border rounded p-3 flex items-center gap-2 text-sm text-muted">
                <Spinner />
                {/* The endpoint stamps the planned total upfront; the select activity replaces it with the real count. */}
                {evaluation.total
                    ? `Testing against rated results… ${evaluation.results.length} of ${evaluation.total} done`
                    : 'Starting the test against your rated results…'}
            </div>
        )
    }

    if (evaluation.status === 'failed' && !evaluation.results.length) {
        return (
            <div className="border rounded p-3 text-sm text-muted">
                The test didn't finish. Run it again to check this prompt against your rated results.
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
            {editedSinceTest && (
                <p className="text-xs text-warning m-0">
                    You've edited fields since this test ran. Test again to see the updated result.
                </p>
            )}
            <div className="flex flex-wrap items-center gap-2 text-sm">
                {isPreview ? (
                    <span className="font-medium">
                        Tested {evaluation.results.length} rated result
                        {evaluation.results.length === 1 ? '' : 's'}. Compare before and after below.
                    </span>
                ) : (
                    <>
                        <span className="font-medium">Tested against {evaluation.results.length} rated results:</span>
                        {downTotal > 0 && (
                            <Tooltip title="Results you rated wrong that changed under the suggested prompt">
                                <LemonTag type={summary.fixed > 0 ? 'success' : 'muted'}>
                                    {summary.fixed} of {downTotal} wrong results changed
                                </LemonTag>
                            </Tooltip>
                        )}
                        {upTotal > 0 && (
                            <Tooltip title="Results you rated right that are unchanged under the suggested prompt">
                                <LemonTag type={summary.regressed > 0 ? 'danger' : 'success'}>
                                    {summary.kept} of {upTotal} right results kept
                                </LemonTag>
                            </Tooltip>
                        )}
                        {summary.errors > 0 && <LemonTag type="muted">{summary.errors} failed to run</LemonTag>}
                    </>
                )}
                <Tooltip title="Only results that ran successfully count against the Replay vision quota">
                    <span className="text-muted text-xs">
                        {chargedCount} observation{chargedCount === 1 ? '' : 's'} charged to your quota
                    </span>
                </Tooltip>
            </div>
            <LemonButton
                size="xsmall"
                type="tertiary"
                icon={detailsOpen ? <IconChevronDown /> : <IconChevronRight />}
                onClick={() => setDetailsOpen(!detailsOpen)}
                data-attr="vision-calibration-evaluation-details-toggle"
            >
                Per-session results
            </LemonButton>
            {detailsOpen && (
                <LemonTable
                    size="small"
                    columns={
                        [
                            {
                                title: 'Outcome',
                                key: 'outcome',
                                render: (_, result) => (
                                    <LemonTag type={EVALUATION_OUTCOME_TAGS[result.outcome]?.type ?? 'muted'}>
                                        {EVALUATION_OUTCOME_TAGS[result.outcome]?.label ?? result.outcome}
                                    </LemonTag>
                                ),
                            },
                            {
                                title: 'Session',
                                key: 'session',
                                render: (_, result) => (
                                    <Link
                                        onClick={() => openSessionPlayer({ id: result.session_id })}
                                        className="font-mono text-xs whitespace-nowrap"
                                    >
                                        {result.session_id}
                                    </Link>
                                ),
                            },
                            {
                                title: 'Verdict',
                                key: 'rated',
                                render: (_, result) => (result.rated_correct ? 'Right' : 'Wrong'),
                            },
                            {
                                title: 'Current prompt',
                                key: 'before',
                                render: (_, result) => result.before ?? '—',
                            },
                            {
                                title: 'Suggested prompt',
                                key: 'after',
                                render: (_, result) =>
                                    result.after ??
                                    (result.error ? (
                                        <span className="text-muted">Failed: {result.error.slice(0, 80)}</span>
                                    ) : (
                                        '—'
                                    )),
                            },
                        ] as LemonTableColumns<PromptEvaluationResultApi>
                    }
                    dataSource={evaluation.results}
                    rowKey="session_id"
                    embedded
                />
            )}
        </div>
    )
}

function ConfigRecommendationPanel({ scannerId }: { scannerId: string }): JSX.Element {
    const logic = scannerCalibrationLogic({ scannerId })
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
        assembledConfig,
        recommendationEditedSinceTest,
        applyIsNoop,
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
    // `quota` gates the test button (enforcement), `displayQuota` renders spend copy (startup cap applied).
    const { quota, displayQuota } = useValues(visionQuotaLogic)
    const { isDarkModeOn } = useValues(themeLogic)
    // Scorer and summarizer have no discrete outcome, so they preview raw before/after instead of a verdict.
    const previewEvaluation = scanner?.scanner_type === 'scorer' || scanner?.scanner_type === 'summarizer'
    const evaluationSupported =
        scanner?.scanner_type === 'monitor' || scanner?.scanner_type === 'classifier' || previewEvaluation
    // Each re-run is charged like a normal observation of the scanner's model.
    const creditsPerTestSession = scanner ? (OBSERVATION_CREDITS_BY_MODEL[scanner.model] ?? 0) : 0
    const plannedTestCredits = plannedTestSessions * creditsPerTestSession
    const [historyOpen, setHistoryOpen] = useState(false)
    const editDisabledReason = getReplayVisionEditDisabledReason(scanner?.user_access_level)

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
                        ? 'Rate results below to get PostHog AI recommendations here.'
                        : 'No recommendation for the current ratings yet.'}
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
                    data-attr="vision-calibration-generate-suggestion"
                >
                    Generate recommendation
                </LemonButton>
            </div>
        )
    } else if (currentSuggestion.status === 'no_change') {
        body = (
            <div className="space-y-3">
                <p className="text-sm m-0">
                    PostHog AI reviewed your rated results and found no prompt changes to recommend.
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
                    isDarkModeOn={isDarkModeOn}
                    scannerId={scannerId}
                    readOnly={currentSuggestion.status !== 'pending'}
                />
                {currentSuggestion.status === 'pending' && (
                    <SuggestionEvaluationPanel
                        suggestion={currentSuggestion}
                        preview={previewEvaluation}
                        editedSinceTest={recommendationEditedSinceTest}
                    />
                )}
                <div className="flex flex-wrap items-center justify-between gap-2">
                    <SuggestionMeta suggestion={currentSuggestion} />
                    <div className="flex flex-wrap items-center gap-2">
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
                                          ? `Replay vision budget of ${formatCreditCount(quota.credit_limit)} reached. Resets ${dayjs(quota.period_end).format('MMM D')}.`
                                          : quota && quota.remaining !== null && plannedTestCredits > quota.remaining
                                            ? `Only ${formatCreditCount(quota.remaining)} of budget left this billing period. Lower the number of results to test.`
                                            : undefined)
                                }
                                tooltip="Re-runs the scanner with the suggested prompt against your rated results, so you can see what would change. Each tested result is charged like a normal observation."
                                onClick={() => evaluateSuggestion(currentSuggestion.id, assembledConfig)}
                                data-attr="vision-calibration-evaluate-suggestion"
                            >
                                {currentSuggestion.evaluation ? 'Test again' : 'Test against rated results'}
                            </LemonButton>
                        )}
                        {currentSuggestion.status === 'pending' && (
                            <LemonButton
                                size="small"
                                type="tertiary"
                                loading={dismissing}
                                disabledReason={editDisabledReason ?? undefined}
                                onClick={() => dismissSuggestion(currentSuggestion.id)}
                                data-attr="vision-calibration-dismiss-suggestion"
                            >
                                Dismiss
                            </LemonButton>
                        )}
                        {currentSuggestion.status === 'pending' && (
                            <LemonButton
                                size="small"
                                type="primary"
                                loading={applying}
                                disabledReason={
                                    editDisabledReason ??
                                    (applyIsNoop ? 'Your edits match the current config' : undefined)
                                }
                                tooltip="Writes this config to the scanner as a new version"
                                onClick={() => applySuggestion(currentSuggestion.id)}
                                data-attr="vision-calibration-apply-suggestion"
                            >
                                Apply to scanner
                            </LemonButton>
                        )}
                    </div>
                </div>
                {currentSuggestion.status === 'pending' && evaluationSupported && plannedTestSessions > 0 && (
                    <div className="flex items-center justify-end gap-1.5 text-xs text-muted">
                        <span>Test</span>
                        <LemonInput
                            type="number"
                            size="xsmall"
                            min={1}
                            max={Math.min(evaluationSessionCap, ratedCount)}
                            value={plannedTestSessions}
                            onChange={(value) => setTestSessionLimit(value ?? null)}
                            className="w-14"
                            data-attr="vision-calibration-test-session-limit"
                        />
                        <span>
                            of your {Math.min(evaluationSessionCap, ratedCount)} rated result
                            {Math.min(evaluationSessionCap, ratedCount) === 1 ? '' : 's'}, thumbs down first. Costs{' '}
                            {formatCreditCount(plannedTestCredits)}
                            {displayQuota && displayQuota.remaining !== null && displayQuota.credit_limit !== null
                                ? `, ${formatCreditsRange(displayQuota.remaining, displayQuota.credit_limit)} left this billing period`
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
                <span className="text-sm font-medium">Recommendation</span>
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
                            data-attr="vision-calibration-regenerate-suggestion"
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
                    data-attr="vision-calibration-suggestion-history-toggle"
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
                                            isDarkModeOn={isDarkModeOn}
                                            scannerId={scannerId}
                                            readOnly
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

const CHART_MODE_OPTIONS: { value: ChartMode; label: string; tooltip: string; 'data-attr': string }[] = [
    {
        value: 'session',
        label: 'By session day',
        tooltip: 'Ratings placed on the day the session was scanned: how scanner accuracy trends over time',
        'data-attr': 'vision-calibration-chart-mode-session',
    },
    {
        value: 'rating',
        label: 'By rating day',
        tooltip: "Ratings placed on the day they were given or changed: the team's rating activity",
        'data-attr': 'vision-calibration-chart-mode-rating',
    },
]

function RatingsOverTimePanel({ scannerId }: { scannerId: string }): JSX.Element {
    const { labelStats, labelStatsLoading } = useValues(scannerCalibrationLogic({ scannerId }))
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
    const formatChartDay = useMemo(() => buildChartDayFormatter(chart?.dates ?? []), [chart])
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
                    <LemonSegmentedButton size="xsmall" value={mode} onChange={setMode} options={CHART_MODE_OPTIONS} />
                </div>
            </div>
            {versionAccuracy.length > 0 && (
                <div className="flex flex-wrap items-center gap-1.5 text-xs tabular-nums">
                    {versionAccuracy.map((entry) => (
                        <Tooltip
                            key={entry.version}
                            title={
                                entry.pct !== null
                                    ? `${entry.rated} rated of ${entry.scanned} scanned on v${entry.version}. Unrated results don't count toward the percentage.`
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
                    No rated results yet. Rate results below to start tracking scanner accuracy.
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
                                        <div className="space-y-1 max-w-[90vw] sm:max-w-100">
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
                                        data-attr="vision-calibration-version-badge"
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

/** Recurring failure modes summarized from the team's written feedback, so raters know what to look for.
 * Clicking a theme filters the results table below to the sessions behind it. */
function FeedbackThemeChips({
    scannerId,
    feedbackThemes,
}: {
    scannerId: string
    feedbackThemes: FeedbackThemesApi
}): JSX.Element | null {
    const { themeFilter } = useValues(scannerCalibrationLogic({ scannerId }))
    const { setThemeFilter } = useActions(scannerCalibrationLogic({ scannerId }))
    if (feedbackThemes.themes.length === 0) {
        return null
    }
    return (
        <div className="flex flex-wrap items-center gap-1.5">
            <Tooltip title="Recurring failure modes summarized from your team's written feedback. They update with each recommendation and feed into the next one.">
                <span className="text-xs text-muted">Feedback themes:</span>
            </Tooltip>
            {feedbackThemes.themes.map((theme) => {
                const isActive = themeFilter?.theme === theme.theme
                const clickable = theme.sessions.length > 0
                return (
                    <Tooltip
                        key={theme.theme}
                        title={
                            <div className="space-y-1">
                                <div>
                                    {theme.count} feedback comment{theme.count === 1 ? '' : 's'} describe this failure
                                    mode. Watch for it when rating.
                                    {clickable &&
                                        (isActive
                                            ? ' Click to stop filtering by it.'
                                            : ' Click to filter the table to its sessions.')}
                                </div>
                                {/* Index keys: the list is static and never reordered, while two raters can write identical quotes. */}
                                {theme.examples.map((example, index) => (
                                    <div key={index} className="text-muted italic">
                                        "{example}"
                                    </div>
                                ))}
                            </div>
                        }
                    >
                        <LemonTag
                            type={isActive ? 'highlight' : 'muted'}
                            onClick={clickable ? () => setThemeFilter(isActive ? null : theme) : undefined}
                            forceClickable={clickable}
                            data-attr="vision-calibration-feedback-theme"
                        >
                            {theme.theme} · {theme.count}
                        </LemonTag>
                    </Tooltip>
                )
            })}
        </div>
    )
}

/**
 * The scanner's Calibration tab: the current config recommendation (with history), quality over time,
 * and the results still awaiting a rating.
 */
export function ScannerCalibrationTab({ scannerId }: { scannerId: string }): JSX.Element {
    const logic = scannerCalibrationLogic({ scannerId })
    const { observations, observationsLoading, total, page, ratedFilter, sort } = useValues(logic)
    const { setPage, setRatedFilter, setSort, labelChanged } = useActions(logic)
    const { openSessionPlayer } = useActions(sessionPlayerModalLogic)
    const { scanner } = useValues(replayScannerLogic({ id: scannerId }))
    const scannerType = scanner?.scanner_type

    const columns: LemonTableColumns<ReplayObservationApi> = [
        {
            title: 'Session',
            key: 'session',
            width: 260,
            render: (_, obs) => (
                // Open in a new tab so labelers keep their place in the list while reviewing a recording.
                <Link
                    to={urls.replayVisionObservation(obs.id)}
                    target="_blank"
                    targetBlankIcon={false}
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
                <Link to={urls.replayVisionObservation(obs.id)} target="_blank" className="block">
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
            title: 'Verdict',
            key: 'rating',
            width: 160,
            render: (_, obs) => (
                <ObservationLabelControl
                    compact
                    observationId={obs.id}
                    initialLabel={obs.label}
                    onChange={(label) => labelChanged(obs.id, label)}
                    scannerUserAccessLevel={scanner?.user_access_level}
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
                    scannerUserAccessLevel={scanner?.user_access_level}
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
                    onClick={() => openSessionPlayer({ id: obs.session_id })}
                    className="whitespace-nowrap"
                    data-attr="vision-calibration-view-recording"
                >
                    View recording
                </LemonButton>
            ),
        },
    ]

    return (
        <div className="flex flex-col gap-6">
            <p className="text-muted m-0">
                Rate scanner results with a thumbs up or down, and add feedback explaining why.
            </p>

            <ConfigRecommendationPanel scannerId={scannerId} />

            <RatingsOverTimePanel scannerId={scannerId} />

            <div className="space-y-3">
                <div className="flex flex-wrap items-start gap-3">
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
                        />
                    </div>
                </div>
                {scanner?.feedback_themes && (
                    <FeedbackThemeChips scannerId={scannerId} feedbackThemes={scanner.feedback_themes} />
                )}
                <LemonTable
                    columns={columns}
                    dataSource={observations}
                    loading={observationsLoading}
                    rowKey="id"
                    pagination={{
                        controlled: true,
                        pageSize: CALIBRATION_PAGE_SIZE,
                        currentPage: page,
                        entryCount: total,
                        onForward: () => setPage(page + 1),
                        onBackward: () => setPage(page - 1),
                        // Page state lives in scannerCalibrationLogic; without this the control also pushes a
                        // `page` URL param that nothing reads and that goes stale on filter or tab changes.
                        useUrl: false,
                    }}
                    sorting={sort}
                    onSort={(next) => setSort(next)}
                    useURLForSorting={false}
                    nouns={['result', 'results']}
                    emptyState={
                        <div className="p-6 text-center text-muted">
                            {ratedFilter === 'rated' ? (
                                'No rated results yet. Rate some under "All" or "Unrated".'
                            ) : ratedFilter === 'unrated' ? (
                                'No unrated results. Everything has been rated.'
                            ) : (
                                <>
                                    No successful observations to rate yet. They'll appear here once the scanner
                                    produces results.{' '}
                                    <VisionDocsLink page="calibration" dataAttr="vision-empty-docs-link-calibration">
                                        Learn how calibration works
                                    </VisionDocsLink>
                                </>
                            )}
                        </div>
                    }
                />
            </div>
        </div>
    )
}
