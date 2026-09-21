import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconChevronDown, IconCopy, IconEye } from '@posthog/icons'
import { LemonButton, LemonInput, LemonTag, Link, Spinner, Tooltip } from '@posthog/lemon-ui'

import { LemonDropdown } from 'lib/lemon-ui/LemonDropdown/LemonDropdown'
import { copyToClipboard } from 'lib/utils/copyToClipboard'
import { cn } from 'lib/utils/css-classes'
import { sessionRecordingPlayerLogic } from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'
import { urls } from 'scenes/urls'

import type { ReplayObservationApi, ReplayScannerApi } from '../generated/api.schemas'
import { observationsDockLogic } from '../logics/observationsDockLogic'
import { visionQuotaLogic } from '../logics/visionQuotaLogic'
import { citedTextToPlainText } from '../utils/citations'
import {
    firstCitationMs,
    isFlaggedObservation,
    isSummaryObservation,
    readModelOutput,
    readReasoning,
    readScore,
    readSummary,
    readTags,
    readTitle,
    readVerdict,
    scannerLabel,
} from '../utils/observation'
import { quotaUx } from '../utils/quotaProjection'
import { ScanBlock, recordingScanBlock } from '../utils/scanEligibility'
import { visionSurfaceShown } from '../utils/visionSurface'
import { CitedText, ObservationStatusTag } from './ObservationCard'
import { ObservationProgressBar } from './ObservationProgressBar'
import { ObservationRetryButton } from './ObservationRetryButton'
import { ObservationTimeline } from './ObservationTimeline'
import { ScannerTypeBadge } from './ScannerTypeBadge'

export function PlayerSidebarObservationsTab(): JSX.Element | null {
    const { sessionRecordingId, logicProps } = useValues(sessionRecordingPlayerLogic)

    // ?tab=observations and the singleton sidebar logic can activate this tab in players whose sidebar never offered it
    if (!visionSurfaceShown(logicProps) || !sessionRecordingId) {
        return null
    }
    return <ObservationsTabContent sessionId={sessionRecordingId} />
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

function VerdictChips({
    observations,
    onSeek,
}: {
    observations: ReplayObservationApi[]
    onSeek: (timestampMs: number) => void
}): JSX.Element | null {
    if (observations.length === 0) {
        return null
    }
    return (
        <div className="flex flex-wrap gap-1" data-attr="vision-verdict-chips">
            {observations.map((observation) => {
                const scannerType = observation.scanner_snapshot?.scanner_type
                const verdict = readVerdict(observation)
                const score = readScore(observation)
                const tags = readTags(observation)
                const value =
                    scannerType === 'monitor'
                        ? verdict
                            ? verdict.charAt(0).toUpperCase() + verdict.slice(1)
                            : '—'
                        : scannerType === 'scorer'
                          ? score !== null
                              ? String(score)
                              : '—'
                          : tags.length > 0
                            ? tags.join(', ')
                            : 'No categories'
                const reasoning = readReasoning(observation)
                const citationMs = firstCitationMs(observation)
                const tooltip = [
                    reasoning
                        ? citedTextToPlainText(reasoning, readModelOutput(observation)?.reasoning_segments)
                        : null,
                    citationMs !== null ? 'Click to jump to the first cited moment.' : null,
                ]
                    .filter(Boolean)
                    .join('\n\n')
                return (
                    <Tooltip key={observation.id} title={tooltip || null}>
                        <LemonTag
                            // A yes verdict isn't inherently good, so no success green.
                            type={isFlaggedObservation(observation) ? 'highlight' : 'default'}
                            onClick={citationMs !== null ? () => onSeek(citationMs) : undefined}
                            forceClickable={citationMs !== null}
                            data-attr="vision-verdict-chip"
                        >
                            <span className="truncate max-w-40">{scannerLabel(observation)}</span>
                            <span className="opacity-60">·</span>
                            <span className="truncate max-w-40">{value}</span>
                        </LemonTag>
                    </Tooltip>
                )
            })}
        </div>
    )
}

function BriefSection({
    observation,
    clampable,
    onSeek,
}: {
    observation: ReplayObservationApi
    clampable: boolean
    onSeek: (timestampMs: number) => void
}): JSX.Element | null {
    const [expanded, setExpanded] = useState(false)
    const title = readTitle(observation)
    const summary = readSummary(observation)
    if (!title && !summary) {
        return null
    }
    const segments = readModelOutput(observation)?.summary_segments
    const clamped = clampable && !expanded
    return (
        <div className="flex flex-col gap-1" data-attr="vision-brief">
            <div className="flex items-center gap-2 min-w-0">
                <span className="text-xs font-semibold uppercase tracking-wide text-secondary">Brief</span>
                <span className="text-xs text-secondary truncate">{scannerLabel(observation)}</span>
                <div className="ml-auto flex items-center gap-1 shrink-0">
                    {summary && (
                        <LemonButton
                            size="xsmall"
                            icon={<IconCopy />}
                            tooltip="Copy brief"
                            onClick={() =>
                                void copyToClipboard(
                                    [title, citedTextToPlainText(summary, segments)].filter(Boolean).join('\n\n'),
                                    'summary'
                                )
                            }
                            data-attr="vision-copy-summary"
                        />
                    )}
                    <Link to={urls.replayVisionObservation(observation.id)} className="text-xs whitespace-nowrap">
                        Details
                    </Link>
                </div>
            </div>
            {title && <span className="text-sm font-semibold">{title}</span>}
            {summary && (
                <p className={cn('text-sm mb-0', clamped ? 'line-clamp-2' : 'whitespace-pre-wrap')}>
                    <CitedText text={summary} segments={segments} onSeek={onSeek} />
                </p>
            )}
            {summary && clampable && (
                <LemonButton
                    size="xsmall"
                    type="tertiary"
                    className="self-start"
                    onClick={() => setExpanded(!expanded)}
                    data-attr="vision-brief-toggle"
                >
                    {expanded ? 'Show less' : 'Show full brief'}
                </LemonButton>
            )}
        </div>
    )
}

function UnsettledRuns({
    observations,
    onRetry,
    retryingIds,
}: {
    observations: ReplayObservationApi[]
    onRetry: (observationId: string) => void
    retryingIds: string[]
}): JSX.Element | null {
    if (observations.length === 0) {
        return null
    }
    return (
        <div className="flex flex-col border-t" data-attr="vision-unsettled-runs">
            {observations.map((observation) => (
                <div key={observation.id} className="flex flex-col gap-1.5 px-2 py-1.5 border-b last:border-b-0">
                    <div className="flex items-center gap-2">
                        <ObservationStatusTag status={observation.status} errorReason={observation.error_reason} />
                        <span className="text-sm truncate flex-1">{scannerLabel(observation)}</span>
                        {observation.error_reason && (
                            <ObservationRetryButton
                                status={observation.status}
                                errorReason={observation.error_reason}
                                onRetry={() => onRetry(observation.id)}
                                loading={retryingIds.includes(observation.id)}
                                size="xsmall"
                                dataAttr="vision-tab-retry-observation"
                            />
                        )}
                        <Link to={urls.replayVisionObservation(observation.id)} className="text-xs whitespace-nowrap">
                            Details
                        </Link>
                    </div>
                    {(observation.status === 'pending' || observation.status === 'running') && (
                        <ObservationProgressBar
                            observationId={observation.id}
                            sessionId={observation.session_id}
                            compact
                        />
                    )}
                </div>
            ))}
        </div>
    )
}

function ObservationsTabContent({ sessionId }: { sessionId: string }): JSX.Element {
    const logic = observationsDockLogic({ sessionId })
    const { observations, observationsLoading, retryingObservationIds, seekbarMarks, hasObservationsInFlight } =
        useValues(logic)
    const { retryObservation } = useActions(logic)
    // The player logic is keyed; seek the exact mounted instance, not a propless default
    const { logicProps, sessionPlayerMetaData } = useValues(sessionRecordingPlayerLogic)
    const seekToTime = (ms: number): void => {
        sessionRecordingPlayerLogic.findMounted(logicProps)?.actions.seekToTime(ms)
    }
    const scanBlock = recordingScanBlock(sessionPlayerMetaData)

    // Every observation lands in exactly one place: brief, chip, or footer line.
    const succeeded = observations.filter((o) => o.status === 'succeeded')
    const brief = succeeded.find(isSummaryObservation) ?? null
    const verdicts = succeeded.filter((o) => !isSummaryObservation(o))
    const unsettled = observations.filter((o) => o.status !== 'succeeded')

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
                    <div className="flex flex-col gap-2 p-2 border-b bg-surface-secondary">
                        <div className="flex items-center">
                            <ScannerPicker sessionId={sessionId} scanBlock={scanBlock} type="secondary" />
                        </div>
                        <VerdictChips observations={verdicts} onSeek={seekToTime} />
                        {brief && (
                            <BriefSection observation={brief} clampable={seekbarMarks.length > 0} onSeek={seekToTime} />
                        )}
                    </div>
                    {seekbarMarks.length > 0 ? (
                        <ObservationTimeline sessionId={sessionId} marks={seekbarMarks} onSeek={seekToTime} />
                    ) : (
                        <div className="flex-1 flex items-center justify-center p-4 text-center text-sm text-muted">
                            {hasObservationsInFlight
                                ? 'Scanning… cited moments will appear here as results land.'
                                : 'No cited moments yet. Run a scanner to add some.'}
                        </div>
                    )}
                    <UnsettledRuns
                        observations={unsettled}
                        onRetry={retryObservation}
                        retryingIds={retryingObservationIds}
                    />
                </>
            )}
        </div>
    )
}
