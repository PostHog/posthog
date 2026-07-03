import { useActions, useValues } from 'kea'
import { useMemo, useState } from 'react'

import { IconRefresh, IconRewindPlay, IconSparkles } from '@posthog/icons'
import { LemonButton, LemonSegmentedButton, LemonTable, LemonTag, LemonTagType, Link, Spinner } from '@posthog/lemon-ui'
import { BarChart, ReferenceLine } from '@posthog/quill-charts'

import { buildTheme } from 'lib/charts/utils/theme'
import { getColorVar } from 'lib/colors'
import { MarkdownTextDiff } from 'lib/components/MarkdownNotebook/MarkdownTextDiff'
import { TZLabel } from 'lib/components/TZLabel'
import { dayjs } from 'lib/dayjs'
import { LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { getAccessControlDisabledReason } from 'lib/utils/accessControlUtils'
import { urls } from 'scenes/urls'

import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { ObservationResultSummary } from '../../components/ObservationCard'
import type { ReplayObservationApi, ReplayScannerPromptSuggestionApi } from '../../generated/api.schemas'
import { ObservationLabelControl, ObservationLabelFeedback } from '../../observations/ObservationLabelControl'
import { fillLabelDays } from '../../utils/labelStats'
import { LABEL_CHART_DAYS, QUALITY_PAGE_SIZE, RatedFilterValue, scannerQualityLogic } from '../scannerQualityLogic'

const RATED_FILTER_OPTIONS: { value: RatedFilterValue; label: string }[] = [
    { value: 'unrated', label: 'Unrated' },
    { value: 'rated', label: 'Rated' },
    { value: 'all', label: 'All' },
]

const SUGGESTION_STATUS_TAGS: Record<string, { type: LemonTagType; label: string }> = {
    applied: { type: 'success', label: 'Applied' },
    dismissed: { type: 'muted', label: 'Dismissed' },
    superseded: { type: 'muted', label: 'Superseded' },
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
    const [historyOpen, setHistoryOpen] = useState(false)
    const editDisabledReason = getAccessControlDisabledReason(
        AccessControlResourceType.SessionRecording,
        AccessControlLevel.Editor
    )

    const statusTag = currentSuggestion ? SUGGESTION_STATUS_TAGS[currentSuggestion.status] : undefined
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
    } else {
        body = (
            <div className="space-y-2">
                {currentSuggestion.rationale && <p className="text-sm m-0">{currentSuggestion.rationale}</p>}
                {currentSuggestion.base_prompt && (
                    <div className="text-xs text-muted">Changes vs the prompt it was generated against:</div>
                )}
                <div className="border rounded bg-surface-secondary p-2 font-mono text-xs whitespace-pre-wrap max-h-48 overflow-y-auto">
                    {currentSuggestion.base_prompt ? (
                        <MarkdownTextDiff
                            before={currentSuggestion.base_prompt}
                            after={currentSuggestion.suggested_prompt}
                        />
                    ) : (
                        currentSuggestion.suggested_prompt
                    )}
                </div>
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
                        {currentSuggestion.status !== 'applied' && (
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
                {statusTag && <LemonTag type={statusTag.type}>{statusTag.label}</LemonTag>}
                {suggestionStale && currentSuggestion && (
                    <LemonTag type="warning">Ratings changed since this was generated</LemonTag>
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
                    onClick={() => {
                        const next = !historyOpen
                        setHistoryOpen(next)
                        if (next && suggestionHistory.length === 0) {
                            loadSuggestionHistory()
                        }
                    }}
                    data-attr="vision-quality-suggestion-history-toggle"
                >
                    {historyOpen ? 'Hide past recommendations' : 'Past recommendations'}
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
                                const tag = SUGGESTION_STATUS_TAGS[suggestion.status]
                                return (
                                    <div key={suggestion.id} className="border rounded p-2 space-y-1">
                                        <div className="flex flex-wrap items-center gap-2">
                                            {tag && <LemonTag type={tag.type}>{tag.label}</LemonTag>}
                                            <SuggestionMeta suggestion={suggestion} />
                                        </div>
                                        {suggestion.rationale && (
                                            <p className="text-xs text-muted m-0">{suggestion.rationale}</p>
                                        )}
                                        <div className="font-mono text-xs whitespace-pre-wrap max-h-24 overflow-y-auto text-muted">
                                            {suggestion.suggested_prompt}
                                        </div>
                                    </div>
                                )
                            })}
                        </div>
                    ))}
            </div>
        </div>
    )
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
    const theme = useMemo(() => buildTheme(), [])
    const [mode, setMode] = useState<ChartMode>('session')
    const chart = useMemo(
        () =>
            labelStats
                ? fillLabelDays(mode === 'session' ? labelStats.by_day : labelStats.by_rating_day, LABEL_CHART_DAYS)
                : null,
        [labelStats, mode]
    )
    // Prompt-version change markers only make sense on the session-day axis.
    const versionMarkers = useMemo(
        () =>
            mode === 'session' && labelStats && chart
                ? labelStats.version_markers
                      .map((marker) => ({ version: marker.version, label: dayjs(marker.date).format('MMM D') }))
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
                        {versionMarkers.map((marker) => (
                            <ReferenceLine
                                key={marker.version}
                                value={marker.label}
                                orientation="vertical"
                                variant="marker"
                                label={`v${marker.version}`}
                            />
                        ))}
                    </BarChart>
                </div>
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
    const { observations, observationsLoading, total, page, ratedFilter } = useValues(logic)
    const { setPage, setRatedFilter, labelChanged } = useActions(logic)

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
            title: 'Created',
            key: 'created_at',
            render: (_, obs) => <TZLabel time={obs.created_at} />,
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
