import { useActions, useValues } from 'kea'
import { type ReactNode, useMemo } from 'react'

import { type RunInteractionLogicProps, runInteractionLogic } from '../logics/runInteractionLogic'
import {
    type ChatActionComposer,
    ChatActionComposerProvider,
    PENDING_REQUEST_REASON,
} from './ChatActionComposerContext'

/**
 * Wires the suggested-action buttons to the runner's composer. Kept as its own component so the draft
 * subscription re-renders this provider only: React skips the memoized `children` element, and only the
 * button rows that consume the context update per keystroke. A read-only view keeps the same tree but
 * provides no composer, so the buttons render disabled.
 */
export function RunChatActionComposerProvider({
    logicProps,
    focusComposer,
    readOnly = false,
    children,
}: {
    logicProps: RunInteractionLogicProps
    /** Moves keyboard focus into the composer, with the caret after the text. */
    focusComposer: () => void
    readOnly?: boolean
    children: ReactNode
}): JSX.Element {
    const logic = runInteractionLogic(logicProps)
    const { composerForm, cancellationState, stagedAttachments, isSubmitting, composerActive } = useValues(logic)
    const { setComposerFormValues, submitComposerForm } = useActions(logic)
    const composerOccupied = composerForm.draft.trim().length > 0 || stagedAttachments.length > 0
    const value = useMemo<ChatActionComposer | null>(() => {
        if (readOnly) {
            return null
        }
        return {
            insert: (message) => {
                const current = currentDraft(logic, logicProps)
                setComposerFormValues({ draft: current.trim() ? `${current.trimEnd()}\n${message}` : message })
                focusComposer()
            },
            send: (message) => {
                if (sendBlockedReason(currentSendState(logic, logicProps))) {
                    return
                }
                setComposerFormValues({ draft: message })
                submitComposerForm()
            },
            sendDisabledReason: sendBlockedReason({
                cancelling: !!cancellationState,
                isSubmitting,
                composerOccupied,
            }),
            // Mirrors the run surface: a pending request hides the composer unless the run is stopping.
            insertDisabledReason: composerActive || cancellationState ? null : PENDING_REQUEST_REASON,
        }
    }, [
        readOnly,
        logic,
        logicProps,
        focusComposer,
        composerOccupied,
        cancellationState,
        isSubmitting,
        composerActive,
        setComposerFormValues,
        submitComposerForm,
    ])
    return <ChatActionComposerProvider value={value}>{children}</ChatActionComposerProvider>
}

interface SendState {
    cancelling: boolean
    isSubmitting: boolean
    composerOccupied: boolean
}

/** Read at click time, after the composer pushes its debounced keystrokes, so none of them is lost. */
function currentDraft(logic: ReturnType<typeof runInteractionLogic>, logicProps: RunInteractionLogicProps): string {
    logicProps.flushDraft?.()
    return logic.values.composerForm.draft
}

/** The rendered disabled reason can lag the last keystrokes, so a click checks the state again. */
function currentSendState(
    logic: ReturnType<typeof runInteractionLogic>,
    logicProps: RunInteractionLogicProps
): SendState {
    const draft = currentDraft(logic, logicProps)
    return {
        cancelling: !!logic.values.cancellationState,
        isSubmitting: logic.values.isSubmitting,
        composerOccupied: draft.trim().length > 0 || logic.values.stagedAttachments.length > 0,
    }
}

function sendBlockedReason({ cancelling, isSubmitting, composerOccupied }: SendState): string | null {
    if (cancelling) {
        return 'Wait for the run to stop'
    }
    if (isSubmitting) {
        return 'Wait for your message to send'
    }
    if (composerOccupied) {
        return 'Send or clear your draft first'
    }
    return null
}
