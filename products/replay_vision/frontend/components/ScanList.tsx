import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { useMemo } from 'react'

import { IconChevronRight } from '@posthog/icons'
import { LemonButton, LemonTag, Link, Tooltip } from '@posthog/lemon-ui'

import { useResizeObserver } from 'lib/hooks/useResizeObserver'
import { cn } from 'lib/utils/css-classes'
import { colonDelimitedDuration } from 'lib/utils/durations'

import type { ReplayObservationApi } from '../generated/api.schemas'
import { observationsDockLogic } from '../logics/observationsDockLogic'
import { SCANNER_TYPE_TAG_TYPE, scannerTypeLabel } from '../replay_scanners/types'
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
import { ObservationProgressBar } from './ObservationProgressBar'
import { ObservationRetryButton } from './ObservationRetryButton'
import { scannerTypeIcon } from './ScannerTypeBadge'

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
            className="pointer-events-none absolute right-8 top-1/2 hidden h-2 w-28 -translate-y-1/2 rounded-sm bg-surface-tertiary @[560px]:block"
            data-attr="vision-scan-moment-ticks"
        >
            {moments.map((ms) => {
                const label = colonDelimitedDuration(Math.floor(ms / 1000), null)
                return (
                    <Tooltip key={ms} title={`Jump to ${label}`}>
                        <button
                            type="button"
                            aria-label={`Jump to ${label}`}
                            onClick={() => onSeek(ms)}
                            className={cn(
                                'pointer-events-auto absolute -top-0.5 h-3 w-1 -translate-x-1/2 cursor-pointer rounded-sm',
                                Math.abs(ms - currentTimeMs) < NEAR_PLAYHEAD_MS ? 'bg-accent' : 'bg-border-bold'
                            )}
                            // eslint-disable-next-line react/forbid-dom-props
                            style={{ left: `${Math.min(100, (ms / endMs) * 100)}%` }}
                            data-attr="vision-scan-moment-tick"
                        />
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
            className="overflow-hidden transition-[height] duration-200 ease-in-out border-t bg-surface-primary"
            // eslint-disable-next-line react/forbid-dom-props
            style={{ height: contentHeight }}
            data-attr="vision-focus-run"
        >
            <div ref={contentRef}>
                {(observation.error_reason || isInFlight(observation)) && (
                    <div className="flex flex-col gap-2 px-3 pb-2">
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
                <div className="flex flex-col gap-2 px-3 py-2">
                    {hasText && (
                        <div className="text-sm max-w-[120ch]">
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
                        className="text-xs self-start"
                    >
                        View details
                    </Link>
                </div>
            </div>
        </div>
    )
}

export interface ScanListProps {
    sessionId: string
    observations: ReplayObservationApi[]
    endMs: number | null
    currentTimeMs: number
    onSeek: (timestampMs: number) => void
}

export function ScanList({ sessionId, observations, endMs, currentTimeMs, onSeek }: ScanListProps): JSX.Element {
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
                    <div key={observation.id} className="border-b border-primary">
                        <div className={cn('relative flex items-center', isFocused && 'bg-fill-highlight-50')}>
                            <LemonButton
                                fullWidth
                                size="small"
                                className="rounded-none min-w-0 flex-1"
                                icon={
                                    scannerType ? (
                                        <Tooltip title={scannerTypeLabel(scannerType)}>
                                            <LemonTag type={SCANNER_TYPE_TAG_TYPE[scannerType]} size="small">
                                                {scannerTypeIcon(scannerType)}
                                            </LemonTag>
                                        </Tooltip>
                                    ) : undefined
                                }
                                sideIcon={<IconChevronRight className={cn(isFocused && 'invisible')} />}
                                onClick={() => focusObservation(observation.id)}
                                aria-expanded={isFocused}
                                data-attr="vision-run-row"
                            >
                                <span
                                    className={cn(
                                        'flex items-center gap-2 min-w-0 w-full font-normal',
                                        ticksEndMs !== null && '@[560px]:pr-32'
                                    )}
                                >
                                    <span className="min-w-0 truncate text-sm @[760px]:shrink-0 @[760px]:max-w-[40%]">
                                        {scannerLabel(observation)}
                                    </span>
                                    <span className="flex items-center gap-2 min-w-0 shrink-0 max-w-[40%]">
                                        <RunResult observation={observation} />
                                    </span>
                                    {!isFocused && observation.summary_line && (
                                        <span className="hidden min-w-0 flex-1 truncate text-xs text-secondary @[760px]:block">
                                            {observation.summary_line}
                                        </span>
                                    )}
                                </span>
                            </LemonButton>
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
