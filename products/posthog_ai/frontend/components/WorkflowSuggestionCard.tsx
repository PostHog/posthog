import { useActions, useValues } from 'kea'
import { useId } from 'react'

import { LemonBanner, LemonLabel, LemonTextArea } from '@posthog/lemon-ui'

import { WORKFLOW_BRIEF_MAX_LENGTH } from 'lib/utils/workflowDraftHandoff'

import { suggestionActionLogic } from '../logics/suggestionActionLogic'
import type { TurnSuggestionLogicProps } from '../logics/turnSuggestionLogic'
import { SuggestionActionRow } from './SuggestionActionRow'

export function WorkflowSuggestionCard(props: TurnSuggestionLogicProps): JSX.Element | null {
    const logic = suggestionActionLogic(props)
    const { suggestion, workflowPrompt, accepted } = useValues(logic)
    const { setWorkflowPrompt } = useActions(logic)
    const briefId = useId()

    if (suggestion?.kind !== 'workflow') {
        return null
    }
    if (accepted) {
        return <LemonBanner type="success">Brief opened in the workflow builder.</LemonBanner>
    }

    return (
        <>
            <div className="flex flex-col gap-1">
                <LemonLabel htmlFor={briefId}>Workflow brief</LemonLabel>
                <LemonTextArea
                    id={briefId}
                    value={workflowPrompt}
                    onChange={setWorkflowPrompt}
                    maxLength={WORKFLOW_BRIEF_MAX_LENGTH}
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
