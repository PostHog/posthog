import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { IconWarning } from '@posthog/icons'
import { Spinner } from '@posthog/lemon-ui'

import { LemonProgress } from 'lib/lemon-ui/LemonProgress'

import { DISPLAY_PHASES } from '../observations/observationProgress'
import { observationProgressLogic } from '../observations/observationProgressLogic'

export function ObservationProgressBar({
    observationId,
    sessionId,
}: {
    observationId: string
    sessionId: string
}): JSX.Element {
    const logic = observationProgressLogic({ observationId, sessionId })
    const { percent, displayPhase, stepNumber, frames, streamError } = useValues(logic)
    const { startStream } = useActions(logic)

    useEffect(() => {
        startStream()
    }, [observationId, startStream])

    if (streamError) {
        // The stream died but the observation may still be running — status polling keeps the page truthful.
        return (
            <div className="flex items-center gap-2 text-muted text-sm">
                <IconWarning className="text-warning text-base shrink-0" />
                <span>Live progress isn't available. This updates when the observation finishes.</span>
            </div>
        )
    }

    return (
        <div className="flex flex-col gap-1.5">
            <div className="flex items-center gap-2 text-muted text-sm">
                <Spinner textColored />
                <span className="min-w-0 truncate">{displayPhase.label}…</span>
            </div>
            <LemonProgress percent={percent} />
            {/* Ticking numbers skip page translation, which would otherwise freeze them and crash React on removal (react#11538). */}
            <div className="flex items-center justify-between gap-2 text-muted text-xs" translate="no">
                <span>
                    Step {stepNumber} of {DISPLAY_PHASES.length}
                </span>
                {frames && (
                    <span>
                        {frames.frame.toLocaleString()} / {frames.estimatedTotalFrames.toLocaleString()} frames
                    </span>
                )}
            </div>
        </div>
    )
}
