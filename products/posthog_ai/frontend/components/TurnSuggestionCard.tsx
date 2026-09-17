import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { IconBell, IconCalendar, IconNotebook, IconTelescope, IconWarning } from '@posthog/icons'

import { TurnSuggestionLogicProps, turnSuggestionLogic } from '../logics/turnSuggestionLogic'
import type { TurnSuggestion } from '../types/streamTypes'
import { AlertSuggestionCard } from './AlertSuggestionCard'
import { ErrorAlertSuggestionCard } from './ErrorAlertSuggestionCard'
import { NotebookSuggestionCard } from './NotebookSuggestionCard'
import { ScoutSuggestionCard } from './ScoutSuggestionCard'
import { SubscriptionSuggestionCard } from './SubscriptionSuggestionCard'
import { SuggestionCardShell } from './SuggestionCardShell'

const CARD_BY_KIND: Record<
    TurnSuggestion['kind'],
    { icon: JSX.Element; Body: (props: TurnSuggestionLogicProps) => JSX.Element | null }
> = {
    scout: { icon: <IconTelescope />, Body: ScoutSuggestionCard },
    notebook: { icon: <IconNotebook />, Body: NotebookSuggestionCard },
    alert: { icon: <IconBell />, Body: AlertSuggestionCard },
    subscription: { icon: <IconCalendar />, Body: SubscriptionSuggestionCard },
    error_alert: { icon: <IconWarning />, Body: ErrorAlertSuggestionCard },
}

export interface TurnSuggestionCardProps extends TurnSuggestionLogicProps {
    isLastTurn: boolean
}

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
    const { icon, Body } = CARD_BY_KIND[suggestion.kind]
    return (
        <div className="animate-fade-in [animation-duration:600ms] motion-reduce:animate-none">
            <SuggestionCardShell
                icon={icon}
                title={suggestion.title}
                description={suggestion.description}
                onDismiss={completed ? undefined : dismiss}
            >
                <Body {...logicProps} />
            </SuggestionCardShell>
        </div>
    )
}
