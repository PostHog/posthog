import { useActions, useValues } from 'kea'
import { useEffect, useMemo, useRef } from 'react'

import { IconChevronRight } from '@posthog/icons'
import { Button, Switch } from '@posthog/quill'

import { useResizeObserver } from 'lib/hooks/useResizeObserver'
import {
    SessionRecordingPlayerLogicProps,
    sessionRecordingPlayerLogic,
} from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'

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
import { QuillRecordingTimeline } from './QuillRecordingTimeline'
import { QuillScannerPicker } from './QuillScannerPicker'
import { ScanList } from './ScanList'

const CURRENT_MOMENT_SELECTOR = '[data-current-moment]'
const FILMSTRIP_MIN_WIDTH_PX = 840

function SectionHeader({ label }: { label: string }): JSX.Element {
    return (
        <div className="flex items-center gap-2 px-3 py-1.5 border-y border-border bg-muted text-xs font-semibold uppercase tracking-wide text-muted-foreground">
            {label}
        </div>
    )
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

/** The observations tab body once observations exist; the host shows the empty and loading states. */
export function QuillRecordingMoments({
    sessionId,
    playerLogicProps,
}: {
    sessionId: string
    playerLogicProps: SessionRecordingPlayerLogicProps
}): JSX.Element {
    const logic = observationsDockLogic({ sessionId })
    const { observations, timeline, followMoments, summarizePending } = useValues(logic)
    const { setFollowMoments, summarize } = useActions(logic)
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
    const filmstrip = width !== undefined && width >= FILMSTRIP_MIN_WIDTH_PX
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
        onSummarize: () => summarize(true),
        summarizing: summarizePending,
        summarizeDisabledReason: scanBlock?.reason ?? quotaDisabledReason,
    }

    return (
        // A container, so long observation text wraps at the panel's width instead of widening it.
        <div ref={rootRef} className="@container flex flex-col flex-1 min-h-0" data-attr="vision-observations-tab">
            <div className="flex items-center gap-2 p-2 border-b border-border bg-muted">
                <QuillScannerPicker sessionId={sessionId} scanBlock={scanBlock} variant="outline" />
                {timelineRows.length > 0 && (
                    <div className="ml-auto flex items-center gap-2">
                        <label className="flex items-center gap-1.5 text-xs">
                            <Switch
                                size="sm"
                                checked={followMoments}
                                onCheckedChange={setFollowMoments}
                                data-attr="vision-follow-moments"
                            />
                            Follow
                        </label>
                        <span className="hidden @[400px]:block">
                            <Button
                                size="sm"
                                variant="outline"
                                disabledReason={nextStopMs !== null ? undefined : 'Nothing later in the recording'}
                                onClick={jumpToNext}
                                data-attr="vision-next-moment"
                            >
                                Next
                                <IconChevronRight />
                            </Button>
                        </span>
                    </div>
                )}
            </div>
            <div className="flex-1 min-h-0 overflow-y-auto" ref={timelineRef}>
                {/* Nothing before the width is known, so posters are fetched once. */}
                {width === undefined ? null : filmstrip ? (
                    <div data-not-quill className="contents">
                        <ChapterFilmstrip {...timelineProps} />
                    </div>
                ) : (
                    <>
                        <SectionHeader label="Timeline" />
                        <QuillRecordingTimeline {...timelineProps} />
                    </>
                )}
                <SectionHeader label="Scans" />
                <div data-not-quill className="contents">
                    <ScanList
                        sessionId={sessionId}
                        observations={observations}
                        endMs={timelineEndMs(timeline, durationMs)}
                        currentTimeMs={currentPlayerTime}
                        onSeek={seekToTime}
                    />
                </div>
            </div>
        </div>
    )
}
