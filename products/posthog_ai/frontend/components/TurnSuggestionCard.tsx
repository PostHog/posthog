import { useValues } from 'kea'
import { useEffect, useState } from 'react'

import { runStreamLogic } from '../logics/runStreamLogic'
import { NotebookSuggestionCard } from './NotebookSuggestionCard'
import { ScoutSuggestionCard } from './ScoutSuggestionCard'

/** Time between the turn's end and the card appearing, so the answer lands before the offer does. */
export const TURN_SUGGESTION_REVEAL_DELAY_MS = 2500

export interface TurnSuggestionCardProps {
    streamKey: string
    turnIndex: number
    isLastTurn: boolean
    /** Task id backing the conversation; the card's analytics events carry it as `task_id`. */
    sessionId: string
    revealDelayMs?: number
}

/**
 * Per-turn slot for the server-classified suggestion. Renders nothing until the classifier has
 * published one for this turn, the turn is the latest, and the reveal delay has passed; then picks
 * the card for the suggestion's kind.
 */
export function TurnSuggestionCard({
    streamKey,
    turnIndex,
    isLastTurn,
    sessionId,
    revealDelayMs = TURN_SUGGESTION_REVEAL_DELAY_MS,
}: TurnSuggestionCardProps): JSX.Element | null {
    const { turnSuggestions } = useValues(runStreamLogic({ streamKey }))
    const suggestion = turnSuggestions[turnIndex] ?? null
    const [revealReady, setRevealReady] = useState(revealDelayMs === 0)

    useEffect(() => {
        if (revealDelayMs === 0) {
            return
        }
        const timer = window.setTimeout(() => setRevealReady(true), revealDelayMs)
        return () => window.clearTimeout(timer)
    }, [revealDelayMs])

    if (!suggestion || !isLastTurn || !revealReady) {
        return null
    }
    return (
        <div className="animate-fade-in [animation-duration:600ms] motion-reduce:animate-none">
            {suggestion.kind === 'scout' ? (
                <ScoutSuggestionCard streamKey={streamKey} turnIndex={turnIndex} sessionId={sessionId} />
            ) : (
                <NotebookSuggestionCard streamKey={streamKey} turnIndex={turnIndex} sessionId={sessionId} />
            )}
        </div>
    )
}
