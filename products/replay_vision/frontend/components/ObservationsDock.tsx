import { useActions, useValues } from 'kea'
import { useRef } from 'react'

import { IconChevronDown, IconEye } from '@posthog/icons'
import { LemonButton, LemonInput, Link, Spinner } from '@posthog/lemon-ui'

import { Resizer } from 'lib/components/Resizer/Resizer'
import { ResizerLogicProps, resizerLogic } from 'lib/components/Resizer/resizerLogic'
import { LemonDropdown } from 'lib/lemon-ui/LemonDropdown/LemonDropdown'
import { sessionRecordingPlayerLogic } from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'
import { urls } from 'scenes/urls'

import type { ReplayScannerApi } from '../generated/api.schemas'
import { observationsDockLogic } from '../logics/observationsDockLogic'
import { visionQuotaLogic } from '../logics/visionQuotaLogic'
import { quotaUx } from '../utils/quotaProjection'
import { ObservationDockCard } from './ObservationCard'

const COLLAPSED_HEIGHT = 44
const DEFAULT_EXPANDED_HEIGHT = 480
const MIN_EXPANDED_HEIGHT = 120
const MAX_EXPANDED_HEIGHT = 800

export function ObservationsDock(): JSX.Element | null {
    const { sessionRecordingId } = useValues(sessionRecordingPlayerLogic)

    if (!sessionRecordingId) {
        return null
    }
    return <ObservationsDockContent sessionId={sessionRecordingId} />
}

/** Searchable scanner picker for "Observe this recording"; a flat menu doesn't scale to teams with many scanners. */
function ScannerPicker({ sessionId }: { sessionId: string }): JSX.Element {
    const logic = observationsDockLogic({ sessionId })
    const { scanners, filteredScanners, scannerSearch, scannerPickerOpen, observing } = useValues(logic)
    const { observe, setScannerSearch, setScannerPickerOpen } = useActions(logic)
    const { quota } = useValues(visionQuotaLogic)
    const { disabledReason: quotaDisabledReason, tooltip: quotaTooltip } = quotaUx(quota)

    return (
        <LemonDropdown
            visible={scannerPickerOpen}
            onVisibilityChange={setScannerPickerOpen}
            closeOnClickInside={false}
            placement="top-start"
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
                        {scanners.length === 0 ? (
                            <Link to={urls.replayVision()} className="block px-2 py-3 text-sm">
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
                                    data-attr="vision-scan-pick-scanner"
                                    data-ph-capture-attribute-scanner-type={scanner.scanner_type}
                                >
                                    <span className="flex items-center justify-between gap-2 w-full">
                                        <span className="truncate">{scanner.name}</span>
                                        <span className="text-muted text-xs shrink-0">{scanner.scanner_type}</span>
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
                type="primary"
                icon={<IconEye />}
                sideIcon={<IconChevronDown />}
                loading={observing}
                disabledReason={quotaDisabledReason}
                tooltip={quotaTooltip}
                data-attr="vision-scan-recording"
            >
                Scan this recording
            </LemonButton>
        </LemonDropdown>
    )
}

function ObservationsDockContent({ sessionId }: { sessionId: string }): JSX.Element {
    const logic = observationsDockLogic({ sessionId })
    const { observations, observationsLoading, dockOpen, retryingObservationIds } = useValues(logic)
    const { setDockOpen, retryObservation } = useActions(logic)
    // sessionRecordingPlayerLogic is keyed by playerKey+sessionRecordingId; seek the exact mounted
    // player by its bound props rather than a propless default instance.
    const { logicProps } = useValues(sessionRecordingPlayerLogic)
    const seekToTime = (ms: number): void => {
        sessionRecordingPlayerLogic.findMounted(logicProps)?.actions.seekToTime(ms)
    }

    const dockRef = useRef<HTMLDivElement>(null)
    const resizerProps: ResizerLogicProps = {
        logicKey: 'vision-observations-dock',
        placement: 'top',
        containerRef: dockRef,
    }
    const { desiredSize, isResizeInProgress } = useValues(resizerLogic(resizerProps))

    const hasContent = observations.length > 0 || observationsLoading
    const expandedHeight = Math.max(
        MIN_EXPANDED_HEIGHT,
        Math.min(MAX_EXPANDED_HEIGHT, desiredSize ?? DEFAULT_EXPANDED_HEIGHT)
    )

    return (
        <div
            ref={dockRef}
            className={`relative border-t bg-surface-primary overflow-hidden flex flex-col ${
                isResizeInProgress ? '' : 'transition-[max-height] duration-300 ease-out'
            }`}
            style={{ maxHeight: dockOpen ? expandedHeight : COLLAPSED_HEIGHT }}
            data-attr="vision-observations-dock"
        >
            {dockOpen && <Resizer {...resizerProps} />}
            <div className="flex items-center gap-3 h-11 px-3 shrink-0">
                <ScannerPicker sessionId={sessionId} />
                {observations.length > 0 && (
                    <span className="text-muted text-sm">
                        {observations.length} observation{observations.length === 1 ? '' : 's'}
                    </span>
                )}
                {hasContent && (
                    <LemonButton
                        className="ml-auto"
                        size="small"
                        icon={<IconChevronDown className={dockOpen ? 'rotate-180' : ''} />}
                        onClick={() => setDockOpen(!dockOpen)}
                        tooltip={dockOpen ? 'Collapse' : 'Expand'}
                        aria-label={dockOpen ? 'Collapse observations' : 'Expand observations'}
                        data-attr="vision-dock-toggle"
                    />
                )}
            </div>
            {dockOpen && (
                <div className="flex-1 overflow-y-auto px-3 pb-3 space-y-2">
                    {observationsLoading && observations.length === 0 ? (
                        <div className="flex items-center gap-2 text-muted py-4">
                            <Spinner /> Loading observations…
                        </div>
                    ) : observations.length === 0 ? (
                        <div className="text-muted text-sm py-4">
                            No observations yet. Pick a scanner to run on this recording.
                        </div>
                    ) : (
                        observations.map((observation) => (
                            <ObservationDockCard
                                key={observation.id}
                                observation={observation}
                                onSeek={seekToTime}
                                onRetry={
                                    observation.status === 'failed' ? () => retryObservation(observation.id) : undefined
                                }
                                retrying={retryingObservationIds.includes(observation.id)}
                            />
                        ))
                    )}
                </div>
            )}
        </div>
    )
}
