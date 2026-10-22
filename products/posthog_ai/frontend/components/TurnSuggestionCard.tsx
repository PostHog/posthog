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
import { SuggestionCardCondensed } from './SuggestionCardCondensed'
import { SuggestionCardShell } from './SuggestionCardShell'

const CARD_BY_KIND: Record<
    TurnSuggestion['kind'],
    { icon: JSX.Element; actionLabel: string; Body: (props: TurnSuggestionLogicProps) => JSX.Element | null }
> = {
    scout: { icon: <IconTelescope />, actionLabel: 'Create scout', Body: ScoutSuggestionCard },
    notebook: { icon: <IconNotebook />, actionLabel: 'Save to notebook', Body: NotebookSuggestionCard },
    alert: { icon: <IconBell />, actionLabel: 'Create alert', Body: AlertSuggestionCard },
    subscription: { icon: <IconCalendar />, actionLabel: 'Subscribe', Body: SubscriptionSuggestionCard },
    error_alert: { icon: <IconWarning />, actionLabel: 'Create alert', Body: ErrorAlertSuggestionCard },
}

export function TurnSuggestionCard(logicProps: TurnSuggestionLogicProps): JSX.Element | null {
    const logic = turnSuggestionLogic(logicProps)
    const { suggestion, visible, completed, expanded, shownSuggestion } = useValues(logic)
    const { dismiss, expand, reportShown } = useActions(logic)

    useEffect(() => {
        // Server frames carry no event id, so a thread that loads the log and then the live tail gets the card frame twice.
        if (visible && suggestion && shownSuggestion?.turnIndex !== suggestion.turnIndex) {
            reportShown(suggestion)
        }
    }, [visible, suggestion, shownSuggestion, reportShown])

    if (!visible || !suggestion) {
        return null
    }
    const { icon, actionLabel, Body } = CARD_BY_KIND[suggestion.kind]
    return (
        <div className="animate-fade-in [animation-duration:600ms] motion-reduce:animate-none">
            {expanded ? (
                <SuggestionCardShell
                    icon={icon}
                    title={suggestion.title}
                    description={suggestion.description}
                    onDismiss={completed ? undefined : dismiss}
                >
                    <Body {...logicProps} />
                </SuggestionCardShell>
            ) : (
                <SuggestionCardCondensed
                    icon={icon}
                    title={suggestion.title}
                    actionLabel={actionLabel}
                    onExpand={expand}
                    onDismiss={dismiss}
                />
            )}
        </div>
    )
}
