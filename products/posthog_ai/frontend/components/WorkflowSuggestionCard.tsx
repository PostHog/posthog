import { useActions, useValues } from 'kea'

import { LemonLabel, LemonTextArea } from '@posthog/lemon-ui'

import { suggestionActionLogic } from '../logics/suggestionActionLogic'
import type { TurnSuggestionLogicProps } from '../logics/turnSuggestionLogic'
import { SuggestionAcceptedBanner } from './SuggestionAcceptedBanner'
import { SuggestionActionRow } from './SuggestionActionRow'

export function WorkflowSuggestionCard(props: TurnSuggestionLogicProps): JSX.Element | null {
    const logic = suggestionActionLogic(props)
    const { suggestion, workflowPrompt, accepted } = useValues(logic)
    const { setWorkflowPrompt } = useActions(logic)

    if (suggestion?.kind !== 'workflow') {
        return null
    }
    if (accepted) {
        return (
            <SuggestionAcceptedBanner accepted={accepted} linkLabel="Open workflow builder">
                Brief opened in the workflow builder.
            </SuggestionAcceptedBanner>
        )
    }

    return (
        <>
            <div className="flex flex-col gap-1">
                <LemonLabel>Workflow brief</LemonLabel>
                <LemonTextArea
                    value={workflowPrompt}
                    onChange={setWorkflowPrompt}
                    maxLength={4000}
                    minRows={3}
                    data-attr="posthog-ai-turn-suggestion-workflow-brief"
                />
            </div>
            <span className="text-xs text-secondary">Review and send the brief in the builder to create a draft.</span>
            <SuggestionActionRow
                {...props}
                label="Open workflow builder"
                dataAttr="posthog-ai-turn-suggestion-open-workflow"
                failedMessage="Couldn't open the workflow builder. Try again."
            />
        </>
    )
}
