import { useActions, useValues } from 'kea'

import { IconChevronDown, IconEye } from '@posthog/icons'
import { LemonButton, LemonInput, Link, Spinner } from '@posthog/lemon-ui'

import { LemonDropdown } from 'lib/lemon-ui/LemonDropdown/LemonDropdown'
import { sessionRecordingPlayerLogic } from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'
import { urls } from 'scenes/urls'

import type { ReplayScannerApi } from '../generated/api.schemas'
import { observationsDockLogic } from '../logics/observationsDockLogic'
import { visionQuotaLogic } from '../logics/visionQuotaLogic'
import { quotaUx } from '../utils/quotaProjection'
import { visionSurfaceShown } from '../utils/visionSurface'
import { ObservationDockCard } from './ObservationCard'

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
    type = 'primary',
    placement = 'bottom-start',
}: {
    sessionId: string
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
                type={type}
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

function ObservationsTabContent({ sessionId }: { sessionId: string }): JSX.Element {
    const logic = observationsDockLogic({ sessionId })
    const { observations, observationsLoading, retryingObservationIds } = useValues(logic)
    const { retryObservation } = useActions(logic)
    // The player logic is keyed; seek the exact mounted instance, not a propless default
    const { logicProps } = useValues(sessionRecordingPlayerLogic)
    const seekToTime = (ms: number): void => {
        sessionRecordingPlayerLogic.findMounted(logicProps)?.actions.seekToTime(ms)
    }

    return (
        <div className="flex flex-col flex-1 min-h-0" data-attr="vision-observations-tab">
            {observationsLoading && observations.length === 0 ? (
                <div className="flex items-center gap-2 text-muted p-4">
                    <Spinner /> Loading observations…
                </div>
            ) : observations.length === 0 ? (
                <div className="flex flex-col flex-1 items-center justify-center gap-2 p-4 text-center">
                    <p className="text-muted text-sm mb-0">
                        No observations yet. Pick a scanner to run on this recording.
                    </p>
                    <ScannerPicker sessionId={sessionId} />
                </div>
            ) : (
                <div className="flex-1 overflow-y-auto p-2 space-y-2">
                    {observations.map((observation) => (
                        <ObservationDockCard
                            key={observation.id}
                            observation={observation}
                            onSeek={seekToTime}
                            onRetry={() => retryObservation(observation.id)}
                            retrying={retryingObservationIds.includes(observation.id)}
                        />
                    ))}
                    <div className="flex justify-center">
                        <ScannerPicker sessionId={sessionId} type="secondary" placement="top-start" />
                    </div>
                </div>
            )}
        </div>
    )
}
