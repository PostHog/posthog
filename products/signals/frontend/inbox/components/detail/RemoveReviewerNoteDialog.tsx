import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonTextArea } from 'lib/lemon-ui/LemonTextArea'

/** Matches `REMOVAL_NOTE_MAX_LENGTH` on the reviewers write serializer. */
const REMOVAL_NOTE_MAX_LENGTH = 500

/**
 * Asks for the note behind a "Something else" removal. Only that menu item opens it, so every other
 * removal stays a single pick from the menu.
 */
export function openRemoveReviewerNoteDialog({
    title,
    onConfirm,
}: {
    title: string
    onConfirm: (note: string) => void
}): void {
    const primaryButtonProps = { children: 'Remove', 'data-attr': 'inbox-remove-reviewer-note-submit' }
    LemonDialog.openForm({
        title,
        description: 'The agent reads your note when it picks reviewers for similar reports.',
        maxWidth: '28rem',
        overlayClassName: '!items-center',
        initialValues: { note: '' },
        content: (
            <LemonField name="note" label="Why?">
                <LemonTextArea
                    // stopPropagation keeps Enter in this multi-line note from submitting the dialog.
                    stopPropagation
                    autoFocus
                    placeholder="For example: I only work on the billing API."
                    maxLength={REMOVAL_NOTE_MAX_LENGTH}
                    minRows={2}
                    maxRows={6}
                />
            </LemonField>
        ),
        errors: {
            note: (note) => (!note?.trim() ? 'Add a note, or pick another reason' : undefined),
        },
        primaryButtonProps,
        onSubmit: ({ note }) => onConfirm(note.trim()),
    })
}
