import { useActions, useValues } from 'kea'
import { useRef } from 'react'

import { IconChevronDown } from '@posthog/icons'
import { LemonButton, Spinner } from '@posthog/lemon-ui'

import { Resizer } from 'lib/components/Resizer/Resizer'
import { ResizerLogicProps, resizerLogic } from 'lib/components/Resizer/resizerLogic'
import { sessionRecordingPlayerLogic } from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'

import { observationsDockLogic } from '../logics/observationsDockLogic'
import { dockObservations, isUnsuccessfulScan } from '../utils/observation'
import { VisionDocsLink } from './DocsLink'
import { ObservationDockCard } from './ObservationCard'
import { SummarizeButton } from './SummarizeButton'
import { SummarizeExplainer } from './SummarizeExplainer'

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

    const shown = dockObservations(observations)
    // Collapsed, the dock is one bar with a caret, so a scan that left no result would sit behind it
    // unseen. The count says there is something to open for; the card inside says which scan and why.
    const unsuccessfulCount = shown.filter(isUnsuccessfulScan).length
    const hasContent = shown.length > 0 || observationsLoading
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
            <div className="flex items-center gap-2 lg:gap-3 h-11 px-3 shrink-0">
                <SummarizeButton sessionId={sessionId} />
                <SummarizeExplainer />
                {hasContent && (
                    <div className="ml-auto flex items-center gap-2 min-w-0">
                        {!dockOpen && unsuccessfulCount > 0 && (
                            <span className="text-muted text-xs truncate" data-attr="vision-dock-no-result-count">
                                No result from {unsuccessfulCount} {unsuccessfulCount === 1 ? 'scan' : 'scans'}
                            </span>
                        )}
                        <LemonButton
                            size="small"
                            icon={<IconChevronDown className={dockOpen ? 'rotate-180' : ''} />}
                            onClick={() => setDockOpen(!dockOpen)}
                            tooltip={dockOpen ? 'Collapse' : 'Expand'}
                            aria-label={dockOpen ? 'Collapse summary' : 'Expand summary'}
                            data-attr="vision-dock-toggle"
                            // This click also sets the auto-expand preference, so which way it went is
                            // the signal for whether people keep summaries open by default.
                            data-ph-capture-attribute-dock-action={dockOpen ? 'collapse' : 'expand'}
                        />
                    </div>
                )}
            </div>
            {dockOpen && (
                <div className="flex-1 overflow-y-auto px-3 pb-3 space-y-2">
                    {observationsLoading && shown.length === 0 ? (
                        <div className="flex items-center gap-2 text-muted py-4">
                            <Spinner /> Loading summaries…
                        </div>
                    ) : shown.length === 0 ? (
                        <div className="text-muted text-sm py-4">
                            No summary yet. Summarize this recording to generate one.{' '}
                            <VisionDocsLink page="observations" dataAttr="vision-empty-docs-link-dock">
                                Learn how observations work
                            </VisionDocsLink>
                        </div>
                    ) : (
                        shown.map((observation) => (
                            <ObservationDockCard
                                key={observation.id}
                                observation={observation}
                                onSeek={seekToTime}
                                onRetry={() => retryObservation(observation.id)}
                                retrying={retryingObservationIds.includes(observation.id)}
                            />
                        ))
                    )}
                </div>
            )}
        </div>
    )
}
