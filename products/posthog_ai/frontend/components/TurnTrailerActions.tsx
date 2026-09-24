import { useMountedLogic, useValues } from 'kea'
import { memo } from 'react'

import { runStreamLogic } from '../logics/runStreamLogic'
import type { RunRef } from '../utils/feedbackEvents'
import type { TurnTrailer } from '../utils/turnTrailers'
import { TurnFeedbackActions } from './TurnFeedbackActions'
import { TurnSuggestionCard } from './TurnSuggestionCard'

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
    const stream = useMountedLogic(runStreamLogic)
    const { turnSuggestion } = useValues(stream)
    return (
        <>
            {turnSuggestion?.turnIndex === trailer.turnIndex ? (
                <TurnSuggestionCard
                    streamKey={stream.props.streamKey}
                    turnIndex={trailer.turnIndex}
                    sessionId={sessionId}
                />
            ) : null}
            <TurnFeedbackActions
                sessionId={sessionId}
                turnIndex={trailer.turnIndex}
                run={run}
                traceId={trailer.traceId}
                turnText={trailer.turnText}
            />
        </>
    )
})
