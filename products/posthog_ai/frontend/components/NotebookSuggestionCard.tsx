import { useActions, useValues } from 'kea'

import { LemonInput, LemonLabel } from '@posthog/lemon-ui'

import { pluralize } from 'lib/utils/strings'

import { suggestionActionLogic } from '../logics/suggestionActionLogic'
import type { TurnSuggestionLogicProps } from '../logics/turnSuggestionLogic'
import { SuggestionAcceptedBanner } from './SuggestionAcceptedBanner'
import { SuggestionActionRow } from './SuggestionActionRow'

export function NotebookSuggestionCard(props: TurnSuggestionLogicProps): JSX.Element | null {
    const logic = suggestionActionLogic(props)
    const { suggestion, notebookTitle, conversationBlocks, accepted } = useValues(logic)
    const { setTitle } = useActions(logic)

    if (suggestion?.kind !== 'notebook') {
        return null
    }
    if (accepted) {
        return (
            <SuggestionAcceptedBanner accepted={accepted} linkLabel="Open notebook">
                Saved to a notebook.
            </SuggestionAcceptedBanner>
        )
    }

    return (
        <>
            <div className="flex flex-col gap-1">
                <LemonLabel>Notebook title</LemonLabel>
                <LemonInput
                    size="small"
                    value={notebookTitle}
                    onChange={setTitle}
                    maxLength={256}
                    data-attr="posthog-ai-turn-suggestion-notebook-title"
                />
            </div>
            <span className="text-xs text-secondary">
                {suggestion.notebook.incident ? 'Saves the timeline, cause and fix, then ' : 'Saves '}
                {pluralize(conversationBlocks.messageCount, 'message')}
                {conversationBlocks.queryCount > 0
                    ? ` and ${pluralize(conversationBlocks.queryCount, 'query', 'queries')}`
                    : ''}
                .
            </span>
            <SuggestionActionRow
                {...props}
                label="Save to notebook"
                dataAttr="posthog-ai-turn-suggestion-save-notebook"
                failedMessage="Couldn't save the notebook. Try again."
            />
        </>
    )
}
