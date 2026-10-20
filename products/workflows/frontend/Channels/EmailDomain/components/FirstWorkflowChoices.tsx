import { useActions, useValues } from 'kea'
import { ReactNode, useEffect, useState } from 'react'

import { IconSparkles } from '@posthog/icons'
import { LemonButton, LemonTag, Tooltip } from '@posthog/lemon-ui'

import { SuggestionCard } from '../../../setupGuide/suggestions/suggestionCards'
import { WorkflowDataSuggestions } from '../../../setupGuide/suggestions/WorkflowDataSuggestions'
import {
    WorkflowDataSuggestionsSurface,
    workflowDataSuggestionsLogic,
} from '../../../setupGuide/suggestions/workflowDataSuggestionsLogic'
import { WorkflowSuggestionCard } from '../../../setupGuide/suggestions/WorkflowSuggestionCard'
import { WorkflowTemplateBlankCard } from '../../../Workflows/templates/WorkflowTemplateBlankCard'
import { emailDomainLogic } from '../emailDomainLogic'
import { CreateWelcomeWorkflowAction } from './CreateWelcomeWorkflowAction'

const SURFACE: WorkflowDataSuggestionsSurface = 'email_domain_wizard'

/** Where the choices show: the last step, or the wait for DNS. Each reports its own data-attrs. */
export type FirstWorkflowChoicesPlacement = 'ready' | 'verifying'

// pinned: data-attr prefixes, autocapture dashboards read them
const DATA_ATTR_PREFIX: Record<FirstWorkflowChoicesPlacement, string> = {
    ready: 'email-domain',
    verifying: 'email-domain-verifying',
}

/** The ways to start a first workflow from the domain wizard: the best suggestion once loaded, else the welcome template and a blank workflow. */
export function FirstWorkflowChoices({
    placement = 'ready',
}: {
    placement?: FirstWorkflowChoicesPlacement
}): JSX.Element {
    const { offersDataSuggestions } = useValues(emailDomainLogic)
    const prefix = DATA_ATTR_PREFIX[placement]

    // The suggestions logic loads on mount, so it only mounts when the organization allows AI processing.
    return offersDataSuggestions ? <ChoicesWithSuggestions prefix={prefix} /> : <TemplateChoices prefix={prefix} />
}

function ChoicesWithSuggestions({ prefix }: { prefix: string }): JSX.Element {
    const { cards, generating } = useValues(workflowDataSuggestionsLogic({ surface: SURFACE }))
    const [skipped, setSkipped] = useState(false)

    if (skipped) {
        return (
            <TemplateChoices prefix={prefix}>
                <LemonButton
                    type="tertiary"
                    size="small"
                    className="self-center"
                    onClick={() => setSkipped(false)}
                    data-attr={`${prefix}-back-to-suggestions`}
                >
                    Back to the suggestions
                </LemonButton>
            </TemplateChoices>
        )
    }
    // Until suggestions load, and when none come back, the welcome template stays the first choice.
    if (generating || cards.length === 0) {
        return (
            <TemplateChoices prefix={prefix}>
                <WorkflowDataSuggestions surface={SURFACE} />
            </TemplateChoices>
        )
    }
    return <SuggestedChoices prefix={prefix} cards={cards} onSkip={() => setSkipped(true)} />
}

function SuggestedChoices({
    prefix,
    cards,
    onSkip,
}: {
    prefix: string
    cards: SuggestionCard[]
    onSkip: () => void
}): JSX.Element {
    const logic = workflowDataSuggestionsLogic({ surface: SURFACE })
    const { buildingKey } = useValues(logic)
    const { reportCardsShown } = useActions(logic)
    const [expanded, setExpanded] = useState(false)
    const [best, ...others] = cards

    // Only the cards on screen count as shown, so expanding reports the rest.
    useEffect(() => {
        reportCardsShown((expanded ? cards : [best]).map((card) => card.suggestionId))
    }, [cards, best, expanded, reportCardsShown])

    return (
        <div className="flex flex-col gap-3" data-attr="workflows-data-suggestions">
            <span className="inline-flex items-center gap-1 self-center text-xs text-tertiary">
                <IconSparkles className="size-3" />
                Suggested from your project's events
                <Tooltip title="AI writes these suggestions from your project's events. Check each draft before you turn it on.">
                    <LemonTag type="completion" size="small">
                        Beta
                    </LemonTag>
                </Tooltip>
            </span>
            <WorkflowSuggestionCard card={best} surface={SURFACE} primary />
            {expanded &&
                others.map((card) => (
                    <WorkflowSuggestionCard key={card.key} card={card} surface={SURFACE} primary={false} />
                ))}
            <div className="flex flex-wrap justify-center gap-x-2">
                {others.length > 0 && !expanded && (
                    <LemonButton
                        type="tertiary"
                        size="small"
                        onClick={() => setExpanded(true)}
                        data-attr={`${prefix}-show-more-suggestions`}
                    >
                        Show {others.length} more {others.length === 1 ? 'suggestion' : 'suggestions'}
                    </LemonButton>
                )}
                <LemonButton
                    type="tertiary"
                    size="small"
                    onClick={onSkip}
                    disabledReason={buildingKey ? 'Wait until the suggested workflow is built' : undefined}
                    data-attr={`${prefix}-skip-suggestions`}
                >
                    Start without a suggestion
                </LemonButton>
            </div>
        </div>
    )
}

function TemplateChoices({ prefix, children }: { prefix: string; children?: ReactNode }): JSX.Element {
    return (
        <div className="flex flex-col gap-5" data-attr={`${prefix}-workflow-choices`}>
            <CreateWelcomeWorkflowAction data-attr={`${prefix}-create-welcome-workflow`} />
            <WorkflowTemplateBlankCard data-attr={`${prefix}-create-blank-workflow`} />
            {children}
        </div>
    )
}
