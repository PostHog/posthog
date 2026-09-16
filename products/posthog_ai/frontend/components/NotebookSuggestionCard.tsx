import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { IconNotebook, IconX } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonInput, LemonLabel } from '@posthog/lemon-ui'

import { pluralize } from 'lib/utils/strings'

import { notebookSuggestionLogic } from '../logics/notebookSuggestionLogic'

export interface NotebookSuggestionCardProps {
    streamKey: string
    turnIndex: number
    sessionId: string
}

export function NotebookSuggestionCard({
    streamKey,
    turnIndex,
    sessionId,
}: NotebookSuggestionCardProps): JSX.Element | null {
    const logic = notebookSuggestionLogic({ streamKey, turnIndex, sessionId })
    const {
        suggestion,
        notebookTitle,
        notebookPreview,
        savedNotebook,
        savedNotebookLoading,
        saveDisabledReason,
        saveError,
        dismissed,
        notebookUrl,
        shownReported,
    } = useValues(logic)
    const { setTitle, dismiss, reportShown, saveNotebook } = useActions(logic)

    useEffect(() => {
        if (suggestion && !shownReported) {
            reportShown()
        }
    }, [suggestion, shownReported, reportShown])

    if (!suggestion || dismissed) {
        return null
    }

    return (
        <div
            className="my-2 flex flex-col gap-3 rounded border bg-surface-primary p-3"
            data-attr="posthog-ai-turn-suggestion"
        >
            <div className="flex items-start gap-2">
                <IconNotebook className="mt-0.5 shrink-0 text-xl text-accent" />
                <div className="min-w-0 flex-1">
                    <div className="font-semibold">{suggestion.title}</div>
                    <div className="text-sm text-secondary">{suggestion.description}</div>
                </div>
                {!savedNotebook && (
                    <LemonButton
                        size="xsmall"
                        type="tertiary"
                        icon={<IconX />}
                        onClick={dismiss}
                        tooltip="Not now"
                        aria-label="Not now"
                        data-attr="posthog-ai-turn-suggestion-dismiss"
                    />
                )}
            </div>

            {savedNotebook ? (
                <LemonBanner
                    type="success"
                    action={notebookUrl ? { to: notebookUrl, children: 'Open notebook' } : undefined}
                >
                    Saved to notebook.
                </LemonBanner>
            ) : (
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
                    {notebookPreview && (
                        <span className="text-xs text-secondary">
                            Saves the conversation so far: {pluralize(notebookPreview.messageCount, 'message')}
                            {notebookPreview.queryCount > 0
                                ? ` and ${pluralize(notebookPreview.queryCount, 'query', 'queries')} as live cells`
                                : ''}
                            .
                        </span>
                    )}
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
            )}
        </div>
    )
}
