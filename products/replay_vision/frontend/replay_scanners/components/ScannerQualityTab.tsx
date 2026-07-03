import { useActions, useValues } from 'kea'
import { useCallback, useEffect, useMemo, useState } from 'react'

import { IconChevronDown, IconChevronRight, IconRefresh, IconRewindPlay, IconSparkles } from '@posthog/icons'
import {
    LemonButton,
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
import { ObservationLabelControl, ObservationLabelFeedback } from '../../observations/ObservationLabelControl'
import { fillLabelDays } from '../../utils/labelStats'
import { replayScannerLogic } from '../replayScannerLogic'
import { replayScannerSceneLogic } from '../replayScannerSceneLogic'
import { LABEL_CHART_DAYS, QUALITY_PAGE_SIZE, RatedFilterValue, scannerQualityLogic } from '../scannerQualityLogic'
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
    return (
        <>
            {suggestion.base_prompt ? (
                <div className="border rounded overflow-hidden">
                    <div className="flex border-b bg-surface-secondary text-xs font-medium">
                        <div className="flex-1 px-3 py-1.5 border-r">{beforeLabel}</div>
                        <div className="flex-1 px-3 py-1.5">Suggested prompt</div>
                    </div>
                    <MonacoDiffEditor
                        original={suggestion.base_prompt}
                        modified={suggestion.suggested_prompt}
                        language="markdown"
                        theme={isDarkModeOn ? 'vs-dark' : 'vs-light'}
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
            <TZLabel time={suggestion.created_at} /> against v{suggestion.scanner_version}
        </span>
    )
}

function PromptRecommendationPanel({ scannerId }: { scannerId: string }): JSX.Element {
    const logic = scannerQualityLogic({ scannerId })
    const {
        currentSuggestion,
        suggestionStale,
        ratedCount,
        suggestionLoading,
        generating,
        applying,
        dismissing,
        suggestionHistory,
        suggestionHistoryLoading,
    } = useValues(logic)
    const { generateSuggestion, applySuggestion, dismissSuggestion, loadSuggestionHistory } = useActions(logic)
    const { isDarkModeOn } = useValues(themeLogic)
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
                <div className="flex flex-wrap items-center justify-between gap-2">
                    <SuggestionMeta suggestion={currentSuggestion} />
                    <div className="flex items-center gap-2">
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
                        {(currentSuggestion.status === 'pending' || currentSuggestion.status === 'dismissed') && (
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
            </div>
        )
    }

    return (
        <div className="border rounded p-4 bg-surface-primary space-y-3">
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
            <div>
                <LemonButton
                    size="xsmall"
                    type="tertiary"
                    icon={historyOpen ? <IconChevronDown /> : <IconChevronRight />}
                    onClick={() => {
                        const next = !historyOpen
                        setHistoryOpen(next)
                        if (next && suggestionHistory.length === 0) {
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
    markers: { version: number; label: string }[]
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
    const { setActiveTab } = useActions(replayScannerSceneLogic)
    const theme = useMemo(() => buildTheme(), [])
    const [mode, setMode] = useState<ChartMode>('session')
    const [badgePositionsRaw, setBadgePositionsRaw] = useState<VersionBadgePosition[]>([])
    // Bail on identical positions so the measure->report->render loop settles instead of cycling.
    const setBadgePositions = useCallback((next: VersionBadgePosition[]) => {
        setBadgePositionsRaw((prev) => (JSON.stringify(prev) === JSON.stringify(next) ? prev : next))
    }, [])
    const badgePositions = mode === 'session' ? badgePositionsRaw : []
    const chart = useMemo(
        () =>
            labelStats
                ? fillLabelDays(mode === 'session' ? labelStats.by_day : labelStats.by_rating_day, LABEL_CHART_DAYS)
                : null,
        [labelStats, mode]
    )
    // Prompt-version markers only make sense on the session-day axis; rendered as badges under the dates.
    const versionMarkers = useMemo(
        () =>
            mode === 'session' && labelStats && chart
                ? labelStats.version_markers
                      .map((marker) => ({
                          version: marker.version,
                          label: dayjs(marker.date).format('MMM D'),
                          prompt: marker.prompt,
                      }))
                      .filter((marker) => chart.labels.includes(marker.label))
                : [],
        [labelStats, chart, mode]
    )
    const totalRated = (labelStats?.up_total ?? 0) + (labelStats?.down_total ?? 0)

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
                            config={{ showGrid: false, barLayout: 'stacked' }}
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
                                        className="absolute top-0 inline-flex cursor-pointer items-center justify-center rounded border bg-surface-secondary px-1.5 py-0.5 text-[10px] font-mono leading-none text-muted hover:text-default"
                                        style={{ left: badge.x, transform: 'translateX(-50%)' }}
                                        onClick={() => setActiveTab('configuration')}
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
        <div className="flex flex-col gap-4">
            <p className="text-muted m-0 max-w-2xl">
                Rate scanner results with a thumbs up or down, and optionally add feedback explaining why. PostHog AI
                turns your team's ratings into the prompt recommendation below.
            </p>

            <PromptRecommendationPanel scannerId={scannerId} />

            <RatingsOverTimePanel scannerId={scannerId} />

            <div className="space-y-2">
                <div className="flex items-start gap-3">
                    <div>
                        <h3 className="font-semibold text-base m-0">Rate results</h3>
                        <p className="text-muted text-xs m-0">
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
