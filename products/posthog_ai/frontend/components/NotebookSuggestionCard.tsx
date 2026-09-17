import { useActions, useValues } from 'kea'

import { LemonBanner, LemonInput, LemonLabel } from '@posthog/lemon-ui'

import { pluralize } from 'lib/utils/strings'

import { suggestionActionLogic } from '../logics/suggestionActionLogic'
import type { TurnSuggestionLogicProps } from '../logics/turnSuggestionLogic'
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
            <LemonBanner
                type="success"
                action={accepted.url ? { to: accepted.url, children: 'Open notebook' } : undefined}
            >
                Saved to notebook.
            </LemonBanner>
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
                {suggestion.notebook.incident
                    ? 'Written up as an incident: timeline, cause, evidence and fix. The evidence is the conversation so far: '
                    : 'Saves the conversation so far: '}
                {pluralize(conversationBlocks.messageCount, 'message')}
                {conversationBlocks.queryCount > 0
                    ? ` and ${pluralize(conversationBlocks.queryCount, 'query', 'queries')} as live cells`
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
