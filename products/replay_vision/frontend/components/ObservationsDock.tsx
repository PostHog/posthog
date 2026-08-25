import { useActions, useValues } from 'kea'
import { useRef, useState } from 'react'

import { IconChevronDown, IconNotebook } from '@posthog/icons'
import { LemonButton, Spinner } from '@posthog/lemon-ui'

import { Resizer } from 'lib/components/Resizer/Resizer'
import { ResizerLogicProps, resizerLogic } from 'lib/components/Resizer/resizerLogic'
import { sessionRecordingPlayerLogic } from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'
import { aiConsentLogic } from 'scenes/settings/organization/aiConsentLogic'
import { AIConsentPopoverWrapper } from 'scenes/settings/organization/AIConsentPopoverWrapper'

import { observationsDockLogic } from '../logics/observationsDockLogic'
import { visionQuotaLogic } from '../logics/visionQuotaLogic'
import { getReplayVisionEditDisabledReason } from '../utils/accessControl'
import { isSummaryObservation } from '../utils/observation'
import { quotaUx } from '../utils/quotaProjection'
import { VisionDocsLink } from './DocsLink'
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

/** One-click summary: an inline summarizer scan, so it needs no saved scanner. */
function SummarizeButton({ sessionId }: { sessionId: string }): JSX.Element {
    const logic = observationsDockLogic({ sessionId })
    const { summarizing } = useValues(logic)
    const { summarize } = useActions(logic)
    const { quota } = useValues(visionQuotaLogic)
    const { dataProcessingAccepted } = useValues(aiConsentLogic)
    const [consentRequested, setConsentRequested] = useState(false)
    const { disabledReason: quotaDisabledReason, tooltip: quotaTooltip } = quotaUx(quota)
    // An inline scan mints a scanner, so the endpoint holds it to scanner-editor access. Without this the
    // button looks available to a viewer and answers 403.
    const accessDisabledReason = getReplayVisionEditDisabledReason()

    const button = (
        <LemonButton
            size="small"
            type="secondary"
            icon={<IconNotebook />}
            loading={summarizing}
            // The endpoint refuses without org AI approval, so ask for it here rather than toasting a 400.
            onClick={() => (dataProcessingAccepted ? summarize() : setConsentRequested(true))}
            disabledReason={accessDisabledReason ?? quotaDisabledReason}
            tooltip={quotaTooltip ?? 'Write a summary of what happened in this recording'}
            data-attr="vision-summarize-recording"
        >
            {dataProcessingAccepted ? 'Summarize this recording' : 'Allow AI analysis and summarize'}
        </LemonButton>
    )

    if (dataProcessingAccepted) {
        return button
    }

    return (
        <AIConsentPopoverWrapper
            placement="bottom-end"
            showArrow
            ignoreDismissal
            hideTrainingDisclaimer
            hidden={!consentRequested}
            onApprove={() => {
                setConsentRequested(false)
                summarize()
            }}
            onDismiss={() => setConsentRequested(false)}
        >
            {button}
        </AIConsentPopoverWrapper>
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

    // Scanner observations live in the sidebar's Observations tab; the dock only surfaces summaries
    const summaries = observations.filter(isSummaryObservation)
    const hasContent = summaries.length > 0 || observationsLoading
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
                {hasContent && (
                    <LemonButton
                        className="ml-auto"
                        size="small"
                        icon={<IconChevronDown className={dockOpen ? 'rotate-180' : ''} />}
                        onClick={() => setDockOpen(!dockOpen)}
                        tooltip={dockOpen ? 'Collapse' : 'Expand'}
                        aria-label={dockOpen ? 'Collapse summary' : 'Expand summary'}
                        data-attr="vision-dock-toggle"
                    />
                )}
            </div>
            {dockOpen && (
                <div className="flex-1 overflow-y-auto px-3 pb-3 space-y-2">
                    {observationsLoading && summaries.length === 0 ? (
                        <div className="flex items-center gap-2 text-muted py-4">
                            <Spinner /> Loading summaries…
                        </div>
                    ) : summaries.length === 0 ? (
                        <div className="text-muted text-sm py-4">
                            No summary yet. Summarize this recording to generate one.{' '}
                            <VisionDocsLink page="observations" dataAttr="vision-empty-docs-link-dock">
                                Learn how observations work
                            </VisionDocsLink>
                        </div>
                    ) : (
                        summaries.map((observation) => (
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
