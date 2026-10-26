import { useActions, useValues } from 'kea'
import { ReactNode, useEffect, useState } from 'react'

import { IconSparkles } from '@posthog/icons'
import { LemonButton, LemonTag, Tooltip } from '@posthog/lemon-ui'

import { SuggestionCard } from '../../../setupGuide/suggestions/suggestionCards'
import { WorkflowDataSuggestions } from '../../../setupGuide/suggestions/WorkflowDataSuggestions'
import {
    WorkflowDataSuggestionsPlacement,
    WorkflowDataSuggestionsSurface,
    workflowDataSuggestionsLogic,
} from '../../../setupGuide/suggestions/workflowDataSuggestionsLogic'
import { WorkflowSuggestionCard } from '../../../setupGuide/suggestions/WorkflowSuggestionCard'
import { WorkflowTemplateBlankCard } from '../../../Workflows/templates/WorkflowTemplateBlankCard'
import { emailDomainLogic } from '../emailDomainLogic'
import { CreateWelcomeWorkflowAction } from './CreateWelcomeWorkflowAction'

const SURFACE: WorkflowDataSuggestionsSurface = 'email_domain_wizard'

// pinned: data-attr prefixes, autocapture dashboards read them
const DATA_ATTR_PREFIX: Record<WorkflowDataSuggestionsPlacement, string> = {
    ready: 'email-domain',
    verifying: 'email-domain-verifying',
}

/** The ways to start a first workflow from the domain wizard: the best suggestion once loaded, else the welcome template and a blank workflow. */
/** Where the choices show, the last step or the wait for DNS, reports its own data-attrs and analytics placement. */
export function FirstWorkflowChoices({
    placement = 'ready',
}: {
    placement?: WorkflowDataSuggestionsPlacement
}): JSX.Element {
    const { offersDataSuggestions } = useValues(emailDomainLogic)

    // The suggestions logic loads on mount, so it only mounts when the organization allows AI processing.
    return offersDataSuggestions ? (
        <ChoicesWithSuggestions placement={placement} />
    ) : (
        <TemplateChoices prefix={DATA_ATTR_PREFIX[placement]} />
    )
}

function ChoicesWithSuggestions({ placement }: { placement: WorkflowDataSuggestionsPlacement }): JSX.Element {
    const { cards, generating } = useValues(workflowDataSuggestionsLogic({ surface: SURFACE }))
    const prefix = DATA_ATTR_PREFIX[placement]
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
    return <SuggestedChoices placement={placement} cards={cards} onSkip={() => setSkipped(true)} />
}

function SuggestedChoices({
    placement,
    cards,
    onSkip,
}: {
    placement: WorkflowDataSuggestionsPlacement
    cards: SuggestionCard[]
    onSkip: () => void
}): JSX.Element {
    const prefix = DATA_ATTR_PREFIX[placement]
    const logic = workflowDataSuggestionsLogic({ surface: SURFACE })
    const { buildingKey } = useValues(logic)
    const { reportCardsShown } = useActions(logic)
    const [expanded, setExpanded] = useState(false)
    const [best, ...others] = cards

    // Only the cards on screen count as shown, so expanding reports the rest.
    useEffect(() => {
        reportCardsShown(
            (expanded ? cards : [best]).map((card) => card.suggestionId),
            placement
        )
    }, [cards, best, expanded, placement, reportCardsShown])

    return (
        <div data-attr={`${prefix}-suggested-workflow-choices`}>
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
                <WorkflowSuggestionCard card={best} surface={SURFACE} placement={placement} primary />
                {expanded &&
                    others.map((card) => (
                        <WorkflowSuggestionCard
                            key={card.key}
                            card={card}
                            surface={SURFACE}
                            placement={placement}
                            primary={false}
                        />
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
