import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { useMemo } from 'react'

import { IconChevronRight } from '@posthog/icons'
import { Button, Tooltip, TooltipContent, TooltipTrigger } from '@posthog/quill'

import { useResizeObserver } from 'lib/hooks/useResizeObserver'
import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { cn } from 'lib/utils/css-classes'
import { colonDelimitedDuration } from 'lib/utils/durations'

import type { ReplayObservationApi } from '../generated/api.schemas'
import { observationsDockLogic } from '../logics/observationsDockLogic'
import { scannerTypeLabel } from '../replay_scanners/types'
import { RECORDING_ORIGIN, currentReturnPath, observationFromOriginUrl } from '../utils/breadcrumbs'
import { isSummaryObservation, readModelOutput, readReasoning, scannerLabel } from '../utils/observation'
import { citedMoments } from '../utils/recordingTimeline'
import { CitedMarkdown } from './CitedMarkdown'
import {
    FailureDetail,
    IneligibleDetail,
    ObservationPrimaryOutput,
    ObservationResultSummary,
    ObservationStatusTag,
} from './ObservationCard'
import { QuillObservationProgressBar } from './QuillObservationProgressBar'
import { QuillObservationRetryButton } from './QuillObservationRetryButton'
import { QuillScannerTypeBadge } from './QuillScannerTypeBadge'

const NEAR_PLAYHEAD_MS = 60_000

const isInFlight = (o: ReplayObservationApi): boolean => o.status === 'pending' || o.status === 'running'

function defaultFocus(observations: ReplayObservationApi[]): ReplayObservationApi | null {
    return (
        observations.find(isInFlight) ?? observations.find((o) => o.status === 'succeeded') ?? observations[0] ?? null
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

function MomentTicks({
    moments,
    endMs,
    currentTimeMs,
    onSeek,
}: {
    moments: number[]
    endMs: number
    currentTimeMs: number
    onSeek: (timestampMs: number) => void
}): JSX.Element {
    return (
        <span
            className="pointer-events-none absolute right-8 top-1/2 hidden h-2 w-28 -translate-y-1/2 rounded-sm bg-muted @[560px]:block"
            data-attr="vision-scan-moment-ticks"
        >
            {moments.map((ms) => {
                const label = colonDelimitedDuration(Math.floor(ms / 1000), null)
                return (
                    <Tooltip key={ms}>
                        <TooltipTrigger
                            render={
                                <Button
                                    size="inline"
                                    aria-label={`Jump to ${label}`}
                                    onClick={() => onSeek(ms)}
                                    className={cn(
                                        'pointer-events-auto absolute -top-0.5 h-3 w-1 min-w-0 -translate-x-1/2 rounded-sm p-0',
                                        Math.abs(ms - currentTimeMs) < NEAR_PLAYHEAD_MS ? 'bg-primary' : 'bg-border'
                                    )}
                                    // eslint-disable-next-line react/forbid-dom-props
                                    style={{ left: `${Math.min(100, (ms / endMs) * 100)}%` }}
                                    data-attr="vision-scan-moment-tick"
                                />
                            }
                        />
                        <TooltipContent>Jump to {label}</TooltipContent>
                    </Tooltip>
                )
            })}
        </span>
    )
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
            className="overflow-hidden transition-[height] duration-200 ease-in-out border-t border-border bg-background"
            // eslint-disable-next-line react/forbid-dom-props
            style={{ height: contentHeight }}
            data-attr="vision-focus-run"
        >
            <div ref={contentRef}>
                {(observation.error_reason || isInFlight(observation)) && (
                    <div className="flex flex-col gap-2 px-3 pb-2">
                        <span data-not-quill className="contents">
                            {observation.status === 'failed' && observation.error_reason && (
                                <FailureDetail errorReason={observation.error_reason} />
                            )}
                            {observation.status === 'ineligible' && observation.error_reason && (
                                <IneligibleDetail errorReason={observation.error_reason} />
                            )}
                        </span>
                        {observation.error_reason && (
                            <div>
                                <QuillObservationRetryButton
                                    status={observation.status}
                                    errorReason={observation.error_reason}
                                    onRetry={onRetry}
                                    loading={retrying}
                                    dataAttr="vision-tab-retry-observation"
                                />
                            </div>
                        )}
                        {isInFlight(observation) && (
                            <QuillObservationProgressBar
                                observationId={observation.id}
                                sessionId={observation.session_id}
                            />
                        )}
                    </div>
                )}
                <div className="flex flex-col gap-2 px-3 py-2">
                    {hasText && (
                        <div className="text-sm max-w-[120ch]" data-not-quill>
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
                    <Button
                        variant="link"
                        size="inline"
                        className="text-xs self-start"
                        render={
                            <LinkPrimitive
                                to={observationFromOriginUrl(
                                    observation.id,
                                    RECORDING_ORIGIN,
                                    currentReturnPath(location)
                                )}
                            />
                        }
                        data-attr="vision-observation-open-from-sidebar"
                    >
                        View details
                    </Button>
                </div>
            </div>
        </div>
    )
}

export function QuillScanList({
    sessionId,
    observations,
    endMs,
    currentTimeMs,
    onSeek,
}: {
    sessionId: string
    observations: ReplayObservationApi[]
    endMs: number | null
    currentTimeMs: number
    onSeek: (timestampMs: number) => void
}): JSX.Element {
    const logic = observationsDockLogic({ sessionId })
    const { focusedObservationId, retryingObservationIds } = useValues(logic)
    const { focusObservation, retryObservation } = useActions(logic)
    const focused = observations.find((o) => o.id === focusedObservationId) ?? defaultFocus(observations)
    const moments = useMemo(() => new Map(observations.map((o) => [o.id, citedMoments(o)])), [observations])
    return (
        <div>
            {observations.map((observation) => {
                const scannerType = observation.scanner_snapshot?.scanner_type
                const isFocused = observation.id === focused?.id
                const ticks = moments.get(observation.id) ?? []
                const ticksEndMs = endMs !== null && ticks.length > 0 ? endMs : null
                return (
                    <div key={observation.id} className="border-b border-border">
                        <div className={cn('relative flex items-center', isFocused && 'bg-fill-selected')}>
                            <Button
                                size="row"
                                left
                                className="rounded-none min-w-0 flex-1 gap-2 font-normal"
                                onClick={() => focusObservation(observation.id)}
                                aria-expanded={isFocused}
                                data-attr="vision-run-row"
                            >
                                {scannerType && (
                                    <Tooltip>
                                        <TooltipTrigger render={<span className="flex shrink-0" />}>
                                            <QuillScannerTypeBadge scannerType={scannerType} iconOnly />
                                        </TooltipTrigger>
                                        <TooltipContent>{scannerTypeLabel(scannerType)}</TooltipContent>
                                    </Tooltip>
                                )}
                                <span
                                    className={cn(
                                        'flex items-center gap-2 min-w-0 flex-1',
                                        ticksEndMs !== null && '@[560px]:pr-32'
                                    )}
                                >
                                    <span className="min-w-0 truncate text-sm @[760px]:shrink-0 @[760px]:max-w-[40%]">
                                        {scannerLabel(observation)}
                                    </span>
                                    <span
                                        className="flex items-center gap-2 min-w-0 shrink-0 max-w-[40%]"
                                        data-not-quill
                                    >
                                        <RunResult observation={observation} />
                                    </span>
                                    {!isFocused && observation.summary_line && (
                                        <span className="hidden min-w-0 flex-1 truncate text-xs text-muted-foreground @[760px]:block">
                                            {observation.summary_line}
                                        </span>
                                    )}
                                </span>
                                <IconChevronRight className={cn('shrink-0', isFocused && 'invisible')} />
                            </Button>
                            {ticksEndMs !== null && (
                                <MomentTicks
                                    moments={ticks}
                                    endMs={ticksEndMs}
                                    currentTimeMs={currentTimeMs}
                                    onSeek={onSeek}
                                />
                            )}
                        </div>
                        {isFocused && (
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
    )
}
