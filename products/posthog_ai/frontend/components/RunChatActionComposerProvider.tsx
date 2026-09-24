import { useActions, useValues } from 'kea'
import { type ReactNode, useMemo } from 'react'

import { type RunInteractionLogicProps, runInteractionLogic } from '../logics/runInteractionLogic'
import { type ChatActionComposer, ChatActionComposerProvider } from './ChatActionComposerContext'

/**
 * Wires the suggested-action buttons to the runner's composer. Kept as its own component so the draft
 * subscription re-renders this provider only: React skips the memoized `children` element, and only the
 * button rows that consume the context update per keystroke.
 */
export function RunChatActionComposerProvider({
    logicProps,
    children,
}: {
    logicProps: RunInteractionLogicProps
    children: ReactNode
}): JSX.Element {
    const logic = runInteractionLogic(logicProps)
    const { composerForm, cancellationState } = useValues(logic)
    const { setComposerFormValues, setComposerFocused, submitComposerForm } = useActions(logic)
    const draft: string = composerForm.draft
    const value = useMemo<ChatActionComposer>(
        () => ({
            insert: (message) => {
                // Read at click time: a keystroke that has not rendered yet must not be lost.
                const current: string = logic.values.composerForm.draft
                setComposerFormValues({ draft: current.trim() ? `${current.trimEnd()}\n${message}` : message })
                setComposerFocused(true)
            },
            send: (message) => {
                setComposerFormValues({ draft: message })
                submitComposerForm()
            },
            sendDisabledReason: cancellationState
                ? 'Wait for the run to stop'
                : draft.trim()
                  ? 'Send or clear your draft first'
                  : null,
        }),
        [logic, draft, cancellationState, setComposerFormValues, setComposerFocused, submitComposerForm]
    )
    return <ChatActionComposerProvider value={value}>{children}</ChatActionComposerProvider>
}
