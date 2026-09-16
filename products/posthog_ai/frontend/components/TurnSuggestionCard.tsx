import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { IconNotebook, IconTelescope } from '@posthog/icons'

import { TurnSuggestionLogicProps, turnSuggestionLogic } from '../logics/turnSuggestionLogic'
import { NotebookSuggestionCard } from './NotebookSuggestionCard'
import { ScoutSuggestionCard } from './ScoutSuggestionCard'
import { SuggestionCardShell } from './SuggestionCardShell'

export interface TurnSuggestionCardProps extends TurnSuggestionLogicProps {
    isLastTurn: boolean
}

/** Per-turn slot for the server-classified suggestion; only the latest turn mounts anything. */
export function TurnSuggestionCard({ isLastTurn, ...logicProps }: TurnSuggestionCardProps): JSX.Element | null {
    return isLastTurn ? <LatestTurnSuggestion {...logicProps} /> : null
}

function LatestTurnSuggestion(logicProps: TurnSuggestionLogicProps): JSX.Element | null {
    const logic = turnSuggestionLogic(logicProps)
    const { suggestion, visible, completed, shownSuggestion } = useValues(logic)
    const { dismiss, reportShown } = useActions(logic)

    useEffect(() => {
        if (visible && suggestion && shownSuggestion !== suggestion) {
            reportShown(suggestion)
        }
    }, [visible, suggestion, shownSuggestion, reportShown])

    if (!visible || !suggestion) {
        return null
    }
    const cardProps = {
        streamKey: logicProps.streamKey,
        turnIndex: logicProps.turnIndex,
        sessionId: logicProps.sessionId,
    }
    return (
        <div className="animate-fade-in [animation-duration:600ms] motion-reduce:animate-none">
            <SuggestionCardShell
                icon={suggestion.kind === 'scout' ? <IconTelescope /> : <IconNotebook />}
                title={suggestion.title}
                description={suggestion.description}
                onDismiss={completed ? undefined : dismiss}
            >
                {suggestion.kind === 'scout' ? (
                    <ScoutSuggestionCard {...cardProps} />
                ) : (
                    <NotebookSuggestionCard {...cardProps} />
                )}
            </SuggestionCardShell>
        </div>
    )
}
