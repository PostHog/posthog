import { useActions, useValues } from 'kea'
import { useEffect, useMemo, useRef } from 'react'

import { IconChevronRight } from '@posthog/icons'
import { LemonButton, LemonSwitch, Spinner } from '@posthog/lemon-ui'

import { useResizeObserver } from 'lib/hooks/useResizeObserver'
import { cn } from 'lib/utils/css-classes'
import { playerSettingsLogic } from 'scenes/session-recordings/player/playerSettingsLogic'
import {
    SessionRecordingPlayerLogicProps,
    sessionRecordingPlayerLogic,
} from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'
import { playerUsesWatchLayout } from 'scenes/session-recordings/playlist/replayLayout'

import { observationsDockLogic } from '../logics/observationsDockLogic'
import { visionQuotaLogic } from '../logics/visionQuotaLogic'
import { quotaUx } from '../utils/quotaProjection'
import {
    currentRowIndex,
    nextTimelineStopMs,
    timelineEndMs,
    timelineRows as buildTimelineRows,
} from '../utils/recordingTimeline'
import { recordingScanBlock } from '../utils/scanEligibility'
import { ChapterFilmstrip } from './ChapterFilmstrip'
import { RecordingObservationsEmptyState } from './RecordingObservationsEmptyState'
import { RecordingTimeline } from './RecordingTimeline'
import { ScanList } from './ScanList'
import { ScannerPicker } from './ScannerPicker'

const CURRENT_MOMENT_SELECTOR = '[data-current-moment]'
const FILMSTRIP_MIN_WIDTH_PX = 840

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

export interface RecordingMomentsProps {
    sessionId: string
    playerLogicProps: SessionRecordingPlayerLogicProps
}

// Aligned to the card's start, a snap point; a smaller scroll gets snapped back and the card stays clipped.
function scrollIntoStrip(card: HTMLElement): void {
    const strip = card.parentElement
    if (!strip) {
        return
    }
    const cardRect = card.getBoundingClientRect()
    const stripRect = strip.getBoundingClientRect()
    if (cardRect.left < stripRect.left || cardRect.right > stripRect.right) {
        strip.scrollBy({ left: cardRect.left - stripRect.left })
    }
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
    const { width, ref: rootRef } = useResizeObserver<HTMLDivElement>()
    const { logicProps, sessionPlayerMetaData, currentPlayerTime, sessionPlayerData } = useValues(
        sessionRecordingPlayerLogic(playerLogicProps)
    )
    const durationMs = sessionPlayerData.durationMs > 0 ? sessionPlayerData.durationMs : null
    const timelineRows = useMemo(() => buildTimelineRows(timeline, durationMs), [timeline, durationMs])
    const seekToTime = (ms: number): void => {
        sessionRecordingPlayerLogic.findMounted(logicProps)?.actions.seekToTime(ms)
    }
    const scanBlock = recordingScanBlock(sessionPlayerMetaData)
    const filmstrip = inWatchLayout && width !== undefined && width >= FILMSTRIP_MIN_WIDTH_PX
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
        followedIndex.current = null
    }, [filmstrip])

    useEffect(() => {
        if (!followMoments) {
            followedIndex.current = null
            return
        }
        if (currentIndex < 0 || followedIndex.current === currentIndex) {
            return
        }
        const current = timelineRef.current?.querySelector<HTMLElement>(CURRENT_MOMENT_SELECTOR)
        if (!current) {
            return
        }
        followedIndex.current = currentIndex
        if (filmstrip) {
            scrollIntoStrip(current)
        } else {
            current.scrollIntoView({ block: 'nearest' })
        }
    }, [currentIndex, followMoments, filmstrip, width])

    const timelineProps = {
        timeline,
        rows: timelineRows,
        currentTimeMs: currentPlayerTime,
        onSeek: seekToTime,
        onSummarize: () => summarize(inWatchLayout),
        summarizing: summarizePending,
        summarizeDisabledReason: scanBlock?.reason ?? quotaDisabledReason,
    }

    return (
        // A container, so long observation text wraps at the sidebar's width instead of widening the sidebar.
        <div ref={rootRef} className="@container flex flex-col flex-1 min-h-0" data-attr="vision-observations-tab">
            {observationsLoading && observations.length === 0 ? (
                <div className="flex items-center gap-2 text-muted p-4">
                    <Spinner /> Loading observations…
                </div>
            ) : observations.length === 0 ? (
                <RecordingObservationsEmptyState
                    sessionId={sessionId}
                    scanBlock={scanBlock}
                    surface={inWatchLayout ? 'watch' : 'tab'}
                />
            ) : (
                <>
                    <div className="flex items-center gap-2 p-2 border-b bg-surface-secondary">
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
                    <div className="flex-1 min-h-0 overflow-y-auto" ref={timelineRef}>
                        {/* Nothing before the width is known, so posters are fetched once. */}
                        {width === undefined ? null : filmstrip ? (
                            <ChapterFilmstrip {...timelineProps} />
                        ) : (
                            <>
                                <SectionHeader label="Timeline" />
                                <RecordingTimeline {...timelineProps} />
                            </>
                        )}
                        <SectionHeader label="Scans" />
                        <ScanList
                            sessionId={sessionId}
                            observations={observations}
                            endMs={timelineEndMs(timeline, durationMs)}
                            currentTimeMs={currentPlayerTime}
                            onSeek={seekToTime}
                        />
                    </div>
                </>
            )}
        </div>
    )
}
