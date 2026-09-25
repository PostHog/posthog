import { memo } from 'react'

import type { RunRef } from '../utils/feedbackEvents'
import type { TurnTrailer } from '../utils/turnTrailers'
import { TurnFeedbackActions } from './TurnFeedbackActions'

export interface TurnTrailerActionsProps {
    trailer: TurnTrailer
    sessionId: string
    run: RunRef
}

export const TurnTrailerActions = memo(function TurnTrailerActions({
    trailer,
    sessionId,
    run,
}: TurnTrailerActionsProps): JSX.Element {
    return (
        <TurnFeedbackActions
            sessionId={sessionId}
            turnIndex={trailer.turnIndex}
            run={run}
            traceId={trailer.traceId}
            turnText={trailer.turnText}
        />
    )
})
