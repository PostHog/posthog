import { useActions, useValues } from 'kea'

import { LemonBanner, LemonButton, LemonInput, LemonLabel } from '@posthog/lemon-ui'

import { pluralize } from 'lib/utils/strings'

import { notebookSuggestionLogic } from '../logics/notebookSuggestionLogic'
import type { TurnSuggestionLogicProps } from '../logics/turnSuggestionLogic'

export function NotebookSuggestionCard(props: TurnSuggestionLogicProps): JSX.Element | null {
    const logic = notebookSuggestionLogic(props)
    const {
        suggestion,
        notebookTitle,
        conversationBlocks,
        savedNotebook,
        savedNotebookLoading,
        saveDisabledReason,
        saveError,
        notebookUrl,
    } = useValues(logic)
    const { setTitle, saveNotebook } = useActions(logic)

    if (!suggestion) {
        return null
    }
    if (savedNotebook) {
        return (
            <LemonBanner
                type="success"
                action={notebookUrl ? { to: notebookUrl, children: 'Open notebook' } : undefined}
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
                Saves the conversation so far: {pluralize(conversationBlocks.messageCount, 'message')}
                {conversationBlocks.queryCount > 0
                    ? ` and ${pluralize(conversationBlocks.queryCount, 'query', 'queries')} as live cells`
                    : ''}
                .
            </span>
            {saveError && <LemonBanner type="error">Couldn't save the notebook. Try again.</LemonBanner>}
            <div className="flex justify-end">
                <LemonButton
                    type="primary"
                    size="small"
                    onClick={saveNotebook}
                    loading={savedNotebookLoading}
                    disabledReason={saveDisabledReason ?? undefined}
                    data-attr="posthog-ai-turn-suggestion-save-notebook"
                >
                    Save to notebook
                </LemonButton>
            </div>
        </>
    )
}
