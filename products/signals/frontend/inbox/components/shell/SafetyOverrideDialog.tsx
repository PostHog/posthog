import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonTextArea } from 'lib/lemon-ui/LemonTextArea'

interface OpenSafetyOverrideDialogParams {
    reportTitle?: string | null
    /** Why PostHog didn't implement the report on its own (see `safetyOverrideReason`). */
    reason: string
    /** Steering text the caller already collected, so the detail pane's popover text survives. */
    initialNote?: string
}

/**
 * Confirm implementing a report PostHog declined to implement on its own, and collect the steer the
 * run should carry. Resolves the note on confirm, or null if the person backed out.
 *
 * Confirming is one button rather than a typed phrase, because a gate that is tedious to pass is
 * one people route around, and this is the escape hatch for a judge that was wrong.
 */
export function openSafetyOverrideDialog({
    reportTitle,
    reason,
    initialNote = '',
}: OpenSafetyOverrideDialogParams): Promise<string | null> {
    return new Promise((resolve) => {
        // `onAfterClose` runs for a confirm and a dismissal alike, so a closed dialog settles the
        // promise exactly once.
        let confirmedNote: string | null = null
        LemonDialog.openForm({
            title: `Implement "${reportTitle?.trim() ? reportTitle : 'Untitled report'}" anyway?`,
            description: `${reason} Your decision is recorded on the report, and the report moves to ready so merging the pull request resolves it.`,
            maxWidth: '36rem',
            overlayClassName: '!items-center',
            initialValues: { note: initialNote },
            content: (
                <LemonField
                    name="note"
                    label="Instructions for the PostHog agent"
                    info="Optional. Saying what you want changed, or why the safety check was wrong, gives the run a better shot."
                >
                    <LemonTextArea
                        // Keeps Enter in this multi-line note from reaching the dialog form and
                        // starting the run mid-sentence.
                        stopPropagation
                        autoFocus
                        placeholder="What should the agent do, or why was the report safe to act on?"
                        maxLength={4000}
                        minRows={3}
                        maxRows={8}
                    />
                </LemonField>
            ),
            primaryButtonProps: { children: 'Implement anyway' },
            onSubmit: ({ note }) => {
                confirmedNote = (note ?? '').trim()
            },
            onAfterClose: () => resolve(confirmedNote),
        })
    })
}
