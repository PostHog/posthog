import { LemonDialog } from '@posthog/lemon-ui'

import { scoutNotesLogic } from '../../../logics/scoutNotesLogic'
import { ScoutNoteComposer } from './ScoutNoteComposer'

/**
 * The dialog closes itself only once the note saved. A failed request leaves it open with the text
 * still in the composer, so a long note is never lost to a transient error.
 */
function LeaveNoteDialog({
    skillName,
    onSubmit,
}: {
    skillName: string
    onSubmit: (content: string) => Promise<boolean>
}): void {
    let content = ''
    let closeDialog: (() => void) | null = null
    LemonDialog.open({
        title: skillName ? 'Tell this scout something' : 'Tell every scout something',
        description: skillName
            ? 'It picks this up on its next run and folds what it takes from it into what it has learned.'
            : 'Every scout on this project picks this up on its next run.',
        content: (close) => {
            closeDialog = close
            return (
                <ScoutNoteComposer
                    onChange={(value) => {
                        content = value
                    }}
                />
            )
        },
        shouldAwaitSubmit: true,
        primaryButton: {
            children: 'Leave note',
            preventClosing: true,
            onClick: async () => {
                const trimmed = content.trim()
                if (!trimmed) {
                    return
                }
                if (await onSubmit(trimmed)) {
                    closeDialog?.()
                }
            },
        },
        secondaryButton: { children: 'Cancel' },
    })
}

export function openLeaveScoutNoteDialog(skillName: string): void {
    const logic = scoutNotesLogic({ skillName })
    LeaveNoteDialog({
        skillName,
        onSubmit: async (content) => {
            await logic.asyncActions.createNote(content)
            return !logic.values.lastSaveFailed
        },
    })
}
