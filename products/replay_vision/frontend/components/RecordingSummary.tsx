import { useActions, useValues } from 'kea'

import { Spinner } from '@posthog/lemon-ui'

import { observationsDockLogic } from '../logics/observationsDockLogic'
import { dockObservations } from '../utils/observation'
import { ObservationDockCard } from './ObservationCard'
import { SummarizeButton } from './SummarizeButton'
import { SummarizeExplainer } from './SummarizeExplainer'

/**
 * The summarize control and its results for a host that embeds the player without its chrome, where the
 * player's own dock is not shown. Results lay out in the host's flow instead of a resizable dock, so a
 * narrow column can show them without squeezing the video.
 */
export function RecordingSummary({
    sessionId,
    onSeek,
}: {
    sessionId: string
    onSeek?: (timestampMs: number) => void
}): JSX.Element {
    const logic = observationsDockLogic({ sessionId })
    const { observations, observationsLoading, retryingObservationIds } = useValues(logic)
    const { retryObservation } = useActions(logic)

    const shown = dockObservations(observations)

    return (
        <div className="flex flex-col gap-2" data-attr="vision-recording-summary">
            <div className="flex flex-wrap items-center gap-2">
                <SummarizeButton sessionId={sessionId} />
                <SummarizeExplainer />
            </div>
            {observationsLoading && shown.length === 0 ? (
                <div className="flex items-center gap-2 text-muted text-sm">
                    <Spinner /> Loading summaries…
                </div>
            ) : (
                shown.map((observation) => (
                    <ObservationDockCard
                        key={observation.id}
                        observation={observation}
                        onSeek={onSeek}
                        onRetry={() => retryObservation(observation.id)}
                        retrying={retryingObservationIds.includes(observation.id)}
                    />
                ))
            )}
        </div>
    )
}
