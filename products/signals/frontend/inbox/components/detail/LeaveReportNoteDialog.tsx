import { useValues } from 'kea'
import { useState } from 'react'

import { LemonDialog, LemonSelect } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'

import { EVERY_SCOUT, reportNotesLogic } from '../../logics/reportNotesLogic'
import { reportNoteMaxChars } from '../../utils/reportNotes'
import { ScoutNoteComposer } from '../config/scouts/ScoutNoteComposer'

interface ReportNoteDraft {
    content: string
    skillName: string
}

/** The target is preselected, so the person sees who the note reaches before they type it. */
function ReportNoteForm({
    reportId,
    reportScoutName,
    draft,
}: {
    reportId: string
    reportScoutName: string | null
    draft: ReportNoteDraft
}): JSX.Element {
    const { noteTargetOptions, scoutConfigsLoading } = useValues(reportNotesLogic({ reportId, reportScoutName }))
    const [skillName, setSkillName] = useState(draft.skillName)

    return (
        <div className="flex flex-col gap-3">
            <LemonField.Pure label="Send to">
                <LemonSelect
                    value={skillName}
                    options={noteTargetOptions}
                    loading={scoutConfigsLoading}
                    onChange={(value) => {
                        setSkillName(value)
                        draft.skillName = value
                    }}
                    data-attr="inbox-report-note-target"
                />
            </LemonField.Pure>
            <LemonField.Pure label="Note">
                <ScoutNoteComposer
                    maxLength={reportNoteMaxChars(reportId)}
                    placeholder="e.g. this checkout flow is being replaced next month, focus on the new one"
                    onChange={(value) => {
                        draft.content = value
                    }}
                />
            </LemonField.Pure>
        </div>
    )
}

/**
 * The dialog closes itself only once the note saved. A failed request leaves it open with the text
 * still in the composer, so a long note is never lost to a transient error.
 */
export function openLeaveReportNoteDialog({
    reportId,
    reportScoutName,
}: {
    reportId: string
    reportScoutName: string | null
}): void {
    const logic = reportNotesLogic({ reportId, reportScoutName })
    const draft: ReportNoteDraft = { content: '', skillName: reportScoutName ?? EVERY_SCOUT }
    let closeDialog: (() => void) | null = null
    LemonDialog.open({
        title: 'Leave a note for the scouts',
        description:
            'Scouts read their notes at the start of every run. The note stays on this report until you retire it.',
        content: (close) => {
            closeDialog = close
            return <ReportNoteForm reportId={reportId} reportScoutName={reportScoutName} draft={draft} />
        },
        shouldAwaitSubmit: true,
        primaryButton: {
            children: 'Leave note',
            preventClosing: true,
            'data-attr': 'inbox-report-note-submit',
            onClick: async () => {
                const content = draft.content.trim()
                if (!content) {
                    return
                }
                await logic.asyncActions.createNote(content, draft.skillName)
                if (!logic.values.lastSaveFailed) {
                    closeDialog?.()
                }
            },
        },
        secondaryButton: { children: 'Cancel' },
    })
}
