import { useActions, useValues } from 'kea'
import { type ReactNode, forwardRef, useEffect, useMemo, useRef, useState } from 'react'

import { IconChevronDown, IconChevronRight, IconCollapse, IconExpand, IconEye } from '@posthog/icons'
import { LemonBadge, LemonButton, LemonInput, LemonSwitch, LemonTag, Link, Spinner, Tooltip } from '@posthog/lemon-ui'

import { useResizeObserver } from 'lib/hooks/useResizeObserver'
import { LemonDropdown } from 'lib/lemon-ui/LemonDropdown/LemonDropdown'
import { cn } from 'lib/utils/css-classes'
import { sessionRecordingPlayerLogic } from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'
import { urls } from 'scenes/urls'

import type { ReplayObservationApi, ReplayScannerApi } from '../generated/api.schemas'
import { observationsDockLogic } from '../logics/observationsDockLogic'
import { visionQuotaLogic } from '../logics/visionQuotaLogic'
import { SCANNER_TYPE_TAG_TYPE, configFromSnapshot, scannerTypeLabel } from '../replay_scanners/types'
import {
    ObservationSeekbarMark,
    isFlaggedObservation,
    isSummaryObservation,
    observationSeekbarMarks,
    readModelOutput,
    readReasoning,
    scannerLabel,
} from '../utils/observation'
import { currentMarkIndex, nextMarkAfter } from '../utils/observationTimeline'
import { quotaUx } from '../utils/quotaProjection'
import { ScanBlock, recordingScanBlock } from '../utils/scanEligibility'
import { visionSurfaceShown } from '../utils/visionSurface'
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
import { ObservationTimeline } from './ObservationTimeline'
import { ScannerTypeBadge, scannerTypeIcon } from './ScannerTypeBadge'

export function PlayerSidebarObservationsTab(): JSX.Element | null {
    const { sessionRecordingId, logicProps } = useValues(sessionRecordingPlayerLogic)

    // ?tab=observations and the singleton sidebar logic can activate this tab in players whose sidebar never offered it
    if (!visionSurfaceShown(logicProps) || !sessionRecordingId) {
        return null
    }
    return <ObservationsTabContent key={sessionRecordingId} sessionId={sessionRecordingId} />
}

function ScannerPicker({
    sessionId,
    scanBlock,
    type = 'primary',
    placement = 'bottom-start',
}: {
    sessionId: string
    scanBlock: ScanBlock | null
    type?: 'primary' | 'secondary'
    placement?: 'bottom-start' | 'top-start'
}): JSX.Element {
    const logic = observationsDockLogic({ sessionId })
    const { scanners, scannersLoading, filteredScanners, scannerSearch, scannerPickerOpen, observing } =
        useValues(logic)
    const { observe, setScannerSearch, setScannerPickerOpen } = useActions(logic)
    const { quota } = useValues(visionQuotaLogic)
    const { disabledReason: quotaDisabledReason, tooltip: quotaTooltip } = quotaUx(quota)

    return (
        <LemonDropdown
            visible={scannerPickerOpen}
            onVisibilityChange={setScannerPickerOpen}
            closeOnClickInside={false}
            placement={placement}
            overlay={
                <div className="w-80">
                    <div className="p-1 border-b">
                        <LemonInput
                            type="search"
                            size="small"
                            placeholder="Search scanners…"
                            value={scannerSearch}
                            onChange={setScannerSearch}
                            autoFocus
                        />
                    </div>
                    <div className="max-h-80 overflow-y-auto p-1">
                        {scanners.length === 0 && scannersLoading ? (
                            <div className="flex items-center gap-2 px-2 py-3 text-sm text-muted">
                                <Spinner /> Loading scanners…
                            </div>
                        ) : scanners.length === 0 ? (
                            <Link to={urls.replayVision()} target="_blank" className="block px-2 py-3 text-sm">
                                No scanners yet — create one
                            </Link>
                        ) : filteredScanners.length === 0 ? (
                            <div className="px-2 py-3 text-sm text-muted">No scanners match your search.</div>
                        ) : (
                            filteredScanners.map((scanner: ReplayScannerApi) => (
                                <LemonButton
                                    key={scanner.id}
                                    fullWidth
                                    size="small"
                                    onClick={() => observe(scanner.id)}
                                    disabledReason={observing ? 'Starting an observation…' : undefined}
                                    data-attr="vision-scan-pick-scanner"
                                    data-ph-capture-attribute-scanner-type={scanner.scanner_type}
                                >
                                    <span className="flex items-center justify-between gap-2 w-full">
                                        <span className="truncate">{scanner.name}</span>
                                        <span className="shrink-0">
                                            <ScannerTypeBadge scannerType={scanner.scanner_type} size="small" />
                                        </span>
                                    </span>
                                </LemonButton>
                            ))
                        )}
                    </div>
                </div>
            }
        >
            <LemonButton
                size="small"
                type={type}
                icon={<IconEye />}
                sideIcon={<IconChevronDown />}
                loading={observing}
                disabledReason={scanBlock?.reason ?? quotaDisabledReason}
                tooltip={quotaTooltip}
                data-attr="vision-scan-recording"
            >
                Scan this recording
            </LemonButton>
        </LemonDropdown>
    )
}

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
    seekbarMarks,
    onSeek,
}: {
    sessionId: string
    observations: ReplayObservationApi[]
    seekbarMarks: ObservationSeekbarMark[]
    onSeek: (timestampMs: number) => void
}): JSX.Element | null {
    const logic = observationsDockLogic({ sessionId })
    const { focusedObservationId, followMoments, retryingObservationIds } = useValues(logic)
    const { focusObservation, setFollowMoments, retryObservation } = useActions(logic)
    const { currentPlayerTime } = useValues(sessionRecordingPlayerLogic)
    const paneRef = useRef<HTMLDivElement>(null)
    const followedMs = useRef<number | null>(null)
    const marksByRun = useMemo(
        () => new Map(observations.map((o) => [o.id, observationSeekbarMarks([o])])),
        [observations]
    )
    const focused = observations.find((o) => o.id === focusedObservationId) ?? defaultFocus(observations)
    const currentIndex = currentMarkIndex(seekbarMarks, currentPlayerTime)
    const currentMs = currentIndex >= 0 ? seekbarMarks[currentIndex].timestampMs : null

    useEffect(() => {
        if (!followMoments) {
            followedMs.current = null
            return
        }
        if (currentMs === null || followedMs.current === currentMs) {
            return
        }
        const owns = (o: ReplayObservationApi): boolean =>
            marksByRun.get(o.id)?.some((m) => m.timestampMs === currentMs) ?? false
        if (focused && !owns(focused)) {
            const owner = observations.find(owns)
            if (owner) {
                focusObservation(owner.id)
                return
            }
        }
        followedMs.current = currentMs
        paneRef.current?.querySelector<HTMLElement>(CURRENT_MOMENT_SELECTOR)?.scrollIntoView({ block: 'nearest' })
    }, [currentMs, followMoments, focused, observations, marksByRun, focusObservation])

    if (observations.length === 0) {
        return null
    }
    const flaggedCount = observations.filter(isFlaggedObservation).length
    return (
        <div className="flex-1 min-h-0 overflow-y-auto" data-attr="vision-observation-runs">
            {focused && (
                <FocusPane
                    ref={paneRef}
                    sessionId={sessionId}
                    observation={focused}
                    marks={marksByRun.get(focused.id) ?? []}
                    onSeek={onSeek}
                    onRetry={() => retryObservation(focused.id)}
                    retrying={retryingObservationIds.includes(focused.id)}
                />
            )}
            <SectionHeader label="Runs" count={observations.length} className="sticky top-0 z-10">
                {flaggedCount > 0 && (
                    <Tooltip title={`${flaggedCount} flagged`}>
                        <LemonBadge.Number count={flaggedCount} size="small" status="primary" />
                    </Tooltip>
                )}
            </SectionHeader>
            <div>
                {observations.map((observation) => {
                    const count = marksByRun.get(observation.id)?.length ?? 0
                    const scannerType = observation.scanner_snapshot?.scanner_type
                    return (
                        <div
                            key={observation.id}
                            className="border-b border-[var(--color-posthog-3000-300)] dark:border-[var(--color-neutral-cool-700)]"
                        >
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
                                onClick={() => {
                                    focusObservation(observation.id)
                                    setFollowMoments(false)
                                }}
                                data-attr="vision-run-row"
                            >
                                <span className="flex items-center gap-2 min-w-0 w-full font-normal">
                                    <span className="text-sm truncate flex-1">{scannerLabel(observation)}</span>
                                    <span className="flex items-center gap-2 min-w-0 max-w-[60%]">
                                        <RunResult observation={observation} />
                                        {count > 0 && (
                                            <Tooltip title={`${count} cited moment${count === 1 ? '' : 's'}`}>
                                                <LemonBadge.Number
                                                    count={count}
                                                    maxDigits={2}
                                                    size="small"
                                                    status={isFlaggedObservation(observation) ? 'primary' : 'muted'}
                                                />
                                            </Tooltip>
                                        )}
                                    </span>
                                </span>
                            </LemonButton>
                        </div>
                    )
                })}
            </div>
        </div>
    )
}

function SectionHeader({
    label,
    count,
    className,
    children,
}: {
    label: string
    count: number
    className?: string
    children?: ReactNode
}): JSX.Element {
    return (
        <div
            className={cn(
                'flex items-center gap-2 px-3 py-1.5 border-y border-primary bg-surface-tertiary dark:bg-surface-secondary text-xs font-semibold uppercase tracking-wide text-secondary',
                className
            )}
        >
            {label}
            <LemonBadge.Number count={count} maxDigits={2} size="small" status="muted" showZero />
            {children}
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

const FocusPane = forwardRef<
    HTMLDivElement,
    {
        sessionId: string
        observation: ReplayObservationApi
        marks: ObservationSeekbarMark[]
        onSeek: (timestampMs: number) => void
        onRetry: () => void
        retrying: boolean
    }
>(function FocusPane({ sessionId, observation, marks, onSeek, onRetry, retrying }, ref) {
    const [textOpenFor, setTextOpenFor] = useState<string | null>(null)
    const showText = textOpenFor === observation.id
    const { height: contentHeight, ref: contentRef } = useResizeObserver<HTMLDivElement>({ box: 'border-box' })
    const isSummary = isSummaryObservation(observation)
    const reasoning = observation.status === 'succeeded' && !isSummary ? readReasoning(observation) : null
    const hasText = observation.status === 'succeeded' && (isSummary || reasoning !== null)
    const textLabel = isSummary ? 'summary' : 'reasoning'
    const prompt = configFromSnapshot(observation.scanner_snapshot)?.prompt ?? null
    const scannerType = observation.scanner_snapshot?.scanner_type
    return (
        <div
            ref={ref}
            className="overflow-hidden transition-[height] duration-200 ease-in-out border-b"
            // eslint-disable-next-line react/forbid-dom-props
            style={{ height: contentHeight }}
            data-attr="vision-focus-run"
        >
            <div ref={contentRef}>
                <div className="flex items-center gap-2 px-3 py-2">
                    {scannerType && (
                        <Tooltip title={scannerTypeLabel(scannerType)}>
                            <LemonTag type={SCANNER_TYPE_TAG_TYPE[scannerType]} size="small">
                                {scannerTypeIcon(scannerType)}
                            </LemonTag>
                        </Tooltip>
                    )}
                    <Tooltip title={prompt}>
                        <span className="text-sm font-semibold truncate">{scannerLabel(observation)}</span>
                    </Tooltip>
                    <span className="ml-auto shrink-0 min-w-0 max-w-[50%]">
                        <RunResult observation={observation} />
                    </span>
                </div>
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
                            <ObservationProgressBar
                                observationId={observation.id}
                                sessionId={observation.session_id}
                                compact
                            />
                        )}
                    </div>
                )}
                {marks.length > 0 && (
                    <>
                        <SectionHeader label="Moments" count={marks.length} />
                        <ObservationTimeline sessionId={sessionId} marks={marks} onSeek={onSeek} />
                    </>
                )}
                <div className="flex flex-col gap-2 px-2 py-2">
                    {observation.status === 'succeeded' && marks.length === 0 && (
                        <span className="text-xs text-muted">No cited moments.</span>
                    )}
                    <div className="flex items-center gap-2">
                        {hasText && (
                            <LemonButton
                                size="xsmall"
                                type="tertiary"
                                sideIcon={showText ? <IconCollapse /> : <IconExpand />}
                                onClick={() => setTextOpenFor(showText ? null : observation.id)}
                                data-attr="vision-run-text-toggle"
                            >
                                {showText ? `Hide ${textLabel}` : `Show ${textLabel}`}
                            </LemonButton>
                        )}
                        <Link to={urls.replayVisionObservation(observation.id)} className="text-xs ml-auto">
                            View details
                        </Link>
                    </div>
                    {hasText && showText && (
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
                </div>
            </div>
        </div>
    )
})

function ObservationsTabContent({ sessionId }: { sessionId: string }): JSX.Element {
    const logic = observationsDockLogic({ sessionId })
    const { observations, observationsLoading, seekbarMarks, followMoments } = useValues(logic)
    const { setFollowMoments, focusObservation } = useActions(logic)
    const lastJumpMs = useRef<number | null>(null)
    // The player logic is keyed; seek the exact mounted instance, not a propless default
    const { logicProps, sessionPlayerMetaData, currentPlayerTime } = useValues(sessionRecordingPlayerLogic)
    const seekToTime = (ms: number): void => {
        sessionRecordingPlayerLogic.findMounted(logicProps)?.actions.seekToTime(ms)
    }
    const scanBlock = recordingScanBlock(sessionPlayerMetaData)
    // A seek can land short of its target; step from the last jump while still on it.
    const nextFrom =
        lastJumpMs.current !== null && Math.abs(currentPlayerTime - lastJumpMs.current) < 1000
            ? lastJumpMs.current
            : currentPlayerTime
    const nextMoment = nextMarkAfter(seekbarMarks, nextFrom)
    const jumpToNextMoment = (): void => {
        if (!nextMoment) {
            return
        }
        lastJumpMs.current = nextMoment.timestampMs
        seekToTime(nextMoment.timestampMs)
        const owner = observations.find((o) =>
            observationSeekbarMarks([o]).some((m) => m.timestampMs === nextMoment.timestampMs)
        )
        if (owner) {
            focusObservation(owner.id)
        }
    }

    return (
        <div className="flex flex-col flex-1 min-h-0" data-attr="vision-observations-tab">
            {observationsLoading && observations.length === 0 ? (
                <div className="flex items-center gap-2 text-muted p-4">
                    <Spinner /> Loading observations…
                </div>
            ) : observations.length === 0 ? (
                <div className="flex flex-col flex-1 items-center justify-center gap-2 p-4 text-center">
                    {scanBlock ? (
                        // No scanner can clear the gate for this recording, so offering the picker would
                        // only lead to an ineligible result.
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
                        {seekbarMarks.length > 0 && (
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
                                        disabledReason={nextMoment ? undefined : 'No later moments'}
                                        onClick={jumpToNextMoment}
                                        data-attr="vision-next-moment"
                                    >
                                        Next moment
                                    </LemonButton>
                                </span>
                            </div>
                        )}
                    </div>
                    <ObservationRuns
                        sessionId={sessionId}
                        observations={observations}
                        seekbarMarks={seekbarMarks}
                        onSeek={seekToTime}
                    />
                </>
            )}
        </div>
    )
}
