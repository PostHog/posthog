import { useValues } from 'kea'
import { useState } from 'react'

import { LemonCheckbox, LemonDialog, LemonSelect } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'

import { EVERY_SCOUT, reportNoteTargetOptions, reportNotesLogic } from '../../logics/reportNotesLogic'
import { scoutNoteWriteDisabledReason } from '../../logics/scoutNotesLogic'
import { reportNoteMaxChars } from '../../utils/reportNotes'
import { ScoutNoteComposer } from '../config/scouts/ScoutNoteComposer'

interface ReportNoteDraft {
    content: string
    sendToScouts: boolean
    skillName: string
}

function AddReportNoteForm({
    reportId,
    reportScoutName,
    draft,
}: {
    reportId: string
    reportScoutName: string | null
    draft: ReportNoteDraft
}): JSX.Element {
    const { scoutNamesBySkill, scoutConfigsLoading } = useValues(reportNotesLogic({ reportId }))
    const [sendToScouts, setSendToScouts] = useState(draft.sendToScouts)
    const [skillName, setSkillName] = useState(draft.skillName)
    const steerDisabledReason = scoutNoteWriteDisabledReason()

    return (
        <div className="flex flex-col gap-3">
            <LemonField.Pure label="Note">
                <ScoutNoteComposer
                    maxLength={reportNoteMaxChars(reportId)}
                    placeholder="e.g. this checkout flow is being replaced next month"
                    onChange={(value) => {
                        draft.content = value
                    }}
                />
            </LemonField.Pure>
            <LemonCheckbox
                checked={sendToScouts}
                disabledReason={steerDisabledReason}
                onChange={(checked) => {
                    setSendToScouts(checked)
                    draft.sendToScouts = checked
                }}
                label="Also send to the scouts"
                data-attr="inbox-report-note-send-to-scouts"
            />
            {sendToScouts && (
                <LemonField.Pure
                    label="Send to"
                    help="Scouts read the note at the start of every run until you retire it from the activity log."
                >
                    <LemonSelect
                        value={skillName}
                        options={reportNoteTargetOptions(scoutNamesBySkill, reportScoutName)}
                        loading={scoutConfigsLoading}
                        onChange={(value) => {
                            setSkillName(value)
                            draft.skillName = value
                        }}
                        data-attr="inbox-report-note-target"
                    />
                </LemonField.Pure>
            )}
        </div>
    )
}

/**
 * The dialog closes itself only once the note saved. A failed request leaves it open with the text
 * still in the composer, so a long note is never lost to a transient error.
 */
export function openAddReportNoteDialog({
    reportId,
    reportScoutName,
}: {
    reportId: string
    reportScoutName: string | null
}): void {
    const logic = reportNotesLogic({ reportId })
    // A note on a scout's report is most often steering for that scout, so start with it selected
    // when the person is allowed to send one.
    const draft: ReportNoteDraft = {
        content: '',
        sendToScouts: !!reportScoutName && !scoutNoteWriteDisabledReason(),
        skillName: reportScoutName ?? EVERY_SCOUT,
    }
    let closeDialog: (() => void) | null = null
    LemonDialog.open({
        title: 'Add a note',
        description: "The note appears in this report's activity.",
        content: (close) => {
            closeDialog = close
            return <AddReportNoteForm reportId={reportId} reportScoutName={reportScoutName} draft={draft} />
        },
        shouldAwaitSubmit: true,
        primaryButton: {
            children: 'Add note',
            preventClosing: true,
            'data-attr': 'inbox-report-note-submit',
            onClick: async () => {
                const content = draft.content.trim()
                if (!content) {
                    return
                }
                await logic.asyncActions.addNote(content, draft.sendToScouts ? draft.skillName : null, reportScoutName)
                if (!logic.values.lastSaveFailed) {
                    closeDialog?.()
                }
            },
        },
        secondaryButton: { children: 'Cancel' },
    })
}
