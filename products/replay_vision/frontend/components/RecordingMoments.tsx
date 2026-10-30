import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { useEffect, useMemo, useRef } from 'react'

import { IconChevronRight } from '@posthog/icons'
import { LemonButton, LemonSwitch, LemonTag, Link, Spinner, Tooltip } from '@posthog/lemon-ui'

import { useResizeObserver } from 'lib/hooks/useResizeObserver'
import { cn } from 'lib/utils/css-classes'
import { playerSettingsLogic } from 'scenes/session-recordings/player/playerSettingsLogic'
import {
    SessionRecordingPlayerLogicProps,
    sessionRecordingPlayerLogic,
} from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'
import { playerUsesWatchLayout } from 'scenes/session-recordings/playlist/replayLayout'

import type { ReplayObservationApi } from '../generated/api.schemas'
import { observationsDockLogic } from '../logics/observationsDockLogic'
import { visionQuotaLogic } from '../logics/visionQuotaLogic'
import { SCANNER_TYPE_TAG_TYPE, scannerTypeLabel } from '../replay_scanners/types'
import { RECORDING_ORIGIN, currentReturnPath, observationFromOriginUrl } from '../utils/breadcrumbs'
import { isSummaryObservation, readModelOutput, readReasoning, scannerLabel } from '../utils/observation'
import { quotaUx } from '../utils/quotaProjection'
import { currentRowIndex, nextTimelineStopMs, timelineRows as buildTimelineRows } from '../utils/recordingTimeline'
import { recordingScanBlock } from '../utils/scanEligibility'
import { CitedMarkdown } from './CitedMarkdown'
import {
    FailureDetail,
    IneligibleDetail,
    ObservationPrimaryOutput,
    ObservationResultSummary,
    ObservationStatusTag,
} from './ObservationCard'
import { ObservationProgressBar } from './ObservationProgressBar'
import { ObservationRetryButton } from './ObservationRetryButton'
import { RecordingTimeline } from './RecordingTimeline'
import { ScannerPicker } from './ScannerPicker'
import { scannerTypeIcon } from './ScannerTypeBadge'

const CURRENT_MOMENT_SELECTOR = '[data-current-moment]'

const isInFlight = (o: ReplayObservationApi): boolean => o.status === 'pending' || o.status === 'running'

function defaultFocus(observations: ReplayObservationApi[]): ReplayObservationApi | null {
    return (
        observations.find(isInFlight) ?? observations.find((o) => o.status === 'succeeded') ?? observations[0] ?? null
    )
}

function ObservationRuns({
    sessionId,
    observations,
    onSeek,
}: {
    sessionId: string
    observations: ReplayObservationApi[]
    onSeek: (timestampMs: number) => void
}): JSX.Element | null {
    const logic = observationsDockLogic({ sessionId })
    const { focusedObservationId, retryingObservationIds } = useValues(logic)
    const { focusObservation, retryObservation } = useActions(logic)
    if (observations.length === 0) {
        return null
    }
    const focused = observations.find((o) => o.id === focusedObservationId) ?? defaultFocus(observations)
    return (
        <>
            <SectionHeader label="Observations" />
            <div>
                {observations.map((observation) => {
                    const scannerType = observation.scanner_snapshot?.scanner_type
                    return (
                        <div key={observation.id} className="border-b border-primary">
                            <LemonButton
                                fullWidth
                                size="small"
                                className="rounded-none"
                                active={observation.id === focused?.id}
                                icon={
                                    scannerType ? (
                                        <Tooltip title={scannerTypeLabel(scannerType)}>
                                            <LemonTag type={SCANNER_TYPE_TAG_TYPE[scannerType]} size="small">
                                                {scannerTypeIcon(scannerType)}
                                            </LemonTag>
                                        </Tooltip>
                                    ) : undefined
                                }
                                onClick={() => focusObservation(observation.id)}
                                data-attr="vision-run-row"
                            >
                                <span className="flex items-center gap-2 min-w-0 w-full font-normal">
                                    <span className="text-sm truncate flex-1">{scannerLabel(observation)}</span>
                                    <span className="flex items-center gap-2 min-w-0 max-w-[60%]">
                                        <RunResult observation={observation} />
                                    </span>
                                </span>
                            </LemonButton>
                            {observation.id === focused?.id && (
                                <FocusPane
                                    observation={observation}
                                    onSeek={onSeek}
                                    onRetry={() => retryObservation(observation.id)}
                                    retrying={retryingObservationIds.includes(observation.id)}
                                />
                            )}
                        </div>
                    )
                })}
            </div>
        </>
    )
}

function SectionHeader({ label, className }: { label: string; className?: string }): JSX.Element {
    return (
        <div
            className={cn(
                'flex items-center gap-2 px-3 py-1.5 border-y border-primary bg-surface-tertiary dark:bg-surface-secondary text-xs font-semibold uppercase tracking-wide text-secondary',
                className
            )}
        >
            {label}
        </div>
    )
}

function RunResult({ observation }: { observation: ReplayObservationApi }): JSX.Element | null {
    if (observation.status !== 'succeeded') {
        return <ObservationStatusTag status={observation.status} errorReason={observation.error_reason} />
    }
    if (isSummaryObservation(observation)) {
        return null
    }
    return <ObservationResultSummary observation={observation} />
}

function FocusPane({
    observation,
    onSeek,
    onRetry,
    retrying,
}: {
    observation: ReplayObservationApi
    onSeek: (timestampMs: number) => void
    onRetry: () => void
    retrying: boolean
}): JSX.Element {
    const { height: contentHeight, ref: contentRef } = useResizeObserver<HTMLDivElement>({ box: 'border-box' })
    const { location } = useValues(router)
    const isSummary = isSummaryObservation(observation)
    const reasoning = observation.status === 'succeeded' && !isSummary ? readReasoning(observation) : null
    const hasText = observation.status === 'succeeded' && (isSummary || reasoning !== null)
    return (
        <div
            className="overflow-hidden transition-[height] duration-200 ease-in-out border-t bg-surface-primary"
            // eslint-disable-next-line react/forbid-dom-props
            style={{ height: contentHeight }}
            data-attr="vision-focus-run"
        >
            <div ref={contentRef}>
                {(observation.error_reason || isInFlight(observation)) && (
                    <div className="flex flex-col gap-2 px-2 pb-2">
                        {observation.status === 'failed' && observation.error_reason && (
                            <FailureDetail errorReason={observation.error_reason} />
                        )}
                        {observation.status === 'ineligible' && observation.error_reason && (
                            <IneligibleDetail errorReason={observation.error_reason} />
                        )}
                        {observation.error_reason && (
                            <div>
                                <ObservationRetryButton
                                    status={observation.status}
                                    errorReason={observation.error_reason}
                                    onRetry={onRetry}
                                    loading={retrying}
                                    size="xsmall"
                                    dataAttr="vision-tab-retry-observation"
                                />
                            </div>
                        )}
                        {isInFlight(observation) && (
                            <ObservationProgressBar observationId={observation.id} sessionId={observation.session_id} />
                        )}
                    </div>
                )}
                <div className="flex flex-col gap-2 px-2 py-2">
                    {hasText && (
                        <div className="text-sm">
                            {isSummary ? (
                                <ObservationPrimaryOutput
                                    observation={observation}
                                    showPrompt={false}
                                    expandSummary
                                    copyable
                                    onSeek={onSeek}
                                />
                            ) : (
                                <CitedMarkdown
                                    text={reasoning ?? ''}
                                    segments={readModelOutput(observation)?.reasoning_segments}
                                    onSeek={onSeek}
                                />
                            )}
                        </div>
                    )}
                    <Link
                        data-attr="vision-observation-open-from-sidebar"
                        to={observationFromOriginUrl(observation.id, RECORDING_ORIGIN, currentReturnPath(location))}
                        className="text-xs self-end"
                    >
                        View details
                    </Link>
                </div>
            </div>
        </div>
    )
}

export interface RecordingMomentsProps {
    sessionId: string
    playerLogicProps: SessionRecordingPlayerLogicProps
}

export function RecordingMoments({ sessionId, playerLogicProps }: RecordingMomentsProps): JSX.Element {
    const logic = observationsDockLogic({ sessionId })
    const { observations, observationsLoading, timeline, followMoments, summarizePending } = useValues(logic)
    const { setFollowMoments, summarize } = useActions(logic)
    const { replayLayout } = useValues(playerSettingsLogic)
    const inWatchLayout = playerUsesWatchLayout(replayLayout, playerLogicProps)
    const { quota } = useValues(visionQuotaLogic)
    const { disabledReason: quotaDisabledReason } = quotaUx(quota)
    const lastJumpMs = useRef<number | null>(null)
    const timelineRef = useRef<HTMLDivElement>(null)
    const followedIndex = useRef<number | null>(null)
    const { logicProps, sessionPlayerMetaData, currentPlayerTime, sessionPlayerData } = useValues(
        sessionRecordingPlayerLogic(playerLogicProps)
    )
    const durationMs = sessionPlayerData.durationMs > 0 ? sessionPlayerData.durationMs : null
    const timelineRows = useMemo(() => buildTimelineRows(timeline, durationMs), [timeline, durationMs])
    const seekToTime = (ms: number): void => {
        sessionRecordingPlayerLogic.findMounted(logicProps)?.actions.seekToTime(ms)
    }
    const scanBlock = recordingScanBlock(sessionPlayerMetaData)
    // A seek can land short of its target. Step from the last jump while still on it.
    const nextFrom =
        lastJumpMs.current !== null && Math.abs(currentPlayerTime - lastJumpMs.current) < 1000
            ? lastJumpMs.current
            : currentPlayerTime
    const nextStopMs = nextTimelineStopMs(timeline, nextFrom)
    const jumpToNext = (): void => {
        if (nextStopMs === null) {
            return
        }
        lastJumpMs.current = nextStopMs
        seekToTime(nextStopMs)
    }
    const currentIndex = currentRowIndex(timelineRows, currentPlayerTime)

    useEffect(() => {
        if (!followMoments) {
            followedIndex.current = null
            return
        }
        if (currentIndex < 0 || followedIndex.current === currentIndex) {
            return
        }
        followedIndex.current = currentIndex
        timelineRef.current?.querySelector<HTMLElement>(CURRENT_MOMENT_SELECTOR)?.scrollIntoView({ block: 'nearest' })
    }, [currentIndex, followMoments])

    return (
        // A container, so long observation text wraps at the sidebar's width instead of widening the sidebar.
        <div className="@container flex flex-col flex-1 min-h-0" data-attr="vision-observations-tab">
            {observationsLoading && observations.length === 0 ? (
                <div className="flex items-center gap-2 text-muted p-4">
                    <Spinner /> Loading observations…
                </div>
            ) : observations.length === 0 ? (
                <div className="flex flex-col flex-1 items-center justify-center gap-2 p-4 text-center">
                    {scanBlock ? (
                        // No scanner can clear the gate, so the picker would only lead to an ineligible result.
                        <>
                            <p className="text-muted text-sm mb-0" data-attr="vision-observations-tab-skipped">
                                Replay vision skipped this recording, so it has no summary.
                            </p>
                            <p className="text-muted text-xs mb-0">{scanBlock.reason}</p>
                        </>
                    ) : (
                        <>
                            <p className="text-muted text-sm mb-0">
                                No observations yet. Pick a scanner to run on this recording.
                            </p>
                            <ScannerPicker sessionId={sessionId} scanBlock={scanBlock} />
                        </>
                    )}
                </div>
            ) : (
                <>
                    <div className="@container flex items-center gap-2 p-2 border-b bg-surface-secondary">
                        <ScannerPicker sessionId={sessionId} scanBlock={scanBlock} type="secondary" />
                        {timelineRows.length > 0 && (
                            <div className="ml-auto flex items-center gap-2">
                                <LemonSwitch
                                    size="xsmall"
                                    checked={followMoments}
                                    onChange={setFollowMoments}
                                    label="Follow"
                                    data-attr="vision-follow-moments"
                                />
                                <span className="hidden @[400px]:block">
                                    <LemonButton
                                        size="small"
                                        type="secondary"
                                        sideIcon={<IconChevronRight />}
                                        disabledReason={
                                            nextStopMs !== null ? undefined : 'Nothing later in the recording'
                                        }
                                        onClick={jumpToNext}
                                        data-attr="vision-next-moment"
                                    >
                                        Next
                                    </LemonButton>
                                </span>
                            </div>
                        )}
                    </div>
                    <div
                        className={cn(
                            'flex-1 min-h-0 overflow-y-auto grid grid-cols-1 content-start',
                            inWatchLayout &&
                                '@[840px]:content-stretch @[840px]:grid-cols-2 @[840px]:grid-rows-[minmax(0,1fr)] @[840px]:overflow-hidden'
                        )}
                        ref={timelineRef}
                    >
                        <div className={cn(inWatchLayout && '@[840px]:min-h-0 @[840px]:overflow-y-auto')}>
                            <SectionHeader label="Timeline" />
                            <RecordingTimeline
                                timeline={timeline}
                                rows={timelineRows}
                                currentTimeMs={currentPlayerTime}
                                onSeek={seekToTime}
                                onSummarize={() => summarize(inWatchLayout)}
                                summarizing={summarizePending}
                                summarizeDisabledReason={scanBlock?.reason ?? quotaDisabledReason}
                            />
                        </div>
                        <div
                            className={cn(
                                inWatchLayout && '@[840px]:min-h-0 @[840px]:overflow-y-auto @[840px]:border-l'
                            )}
                        >
                            <ObservationRuns sessionId={sessionId} observations={observations} onSeek={seekToTime} />
                        </div>
                    </div>
                </>
            )}
        </div>
    )
}
