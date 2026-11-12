import { useValues } from 'kea'
import { useState } from 'react'

import { LemonButton, LemonCheckbox, LemonInput, LemonSelect } from '@posthog/lemon-ui'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'

import { EVERY_SCOUT, reportNoteTargetOptions, reportNotesLogic } from '../../logics/reportNotesLogic'
import { scoutNoteWriteDisabledReason } from '../../logics/scoutNotesLogic'
import { SignalReport } from '../../types'
import { reportNoteMaxChars } from '../../utils/reportNotes'
import { ScoutNoteComposer } from '../config/scouts/ScoutNoteComposer'
import { QuillReportNoteAddButton } from './QuillReportNoteAddButton'
import { QuillReportNoteComposer } from './QuillReportNoteComposer'

/**
 * The open composer. It mounts the notes logic, so a report that nobody writes a note on never loads
 * the scout fleet for the target picker.
 */
function OpenComposer({ report, onClose }: { report: SignalReport; onClose: () => void }): JSX.Element {
    const reportScoutName = report.scout_name ?? null
    const logic = reportNotesLogic({ reportId: report.id })
    const { scoutNamesBySkill, scoutConfigsLoading, savingNote } = useValues(logic)
    const steerDisabledReason = scoutNoteWriteDisabledReason()
    const [text, setText] = useState('')
    // A note on a scout's report is most often steering for that scout, so start with it selected
    // when the person is allowed to send one.
    const [sendToScouts, setSendToScouts] = useState(!!reportScoutName && !steerDisabledReason)
    const [skillName, setSkillName] = useState(reportScoutName ?? EVERY_SCOUT)
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')
    const maxLength = reportNoteMaxChars(report.id)
    const placeholder = 'e.g. this checkout flow is being replaced next month'
    const targetOptions = reportNoteTargetOptions(scoutNamesBySkill, reportScoutName)

    const submit = async (): Promise<void> => {
        await logic.asyncActions.addNote(text.trim(), sendToScouts ? skillName : null, reportScoutName)
        // A failed save keeps the composer open with the text, so a long note is never lost.
        if (!logic.values.lastSaveFailed) {
            onClose()
        }
    }

    if (todayRailNav) {
        return (
            <QuillReportNoteComposer
                text={text}
                onTextChange={setText}
                maxLength={maxLength}
                placeholder={placeholder}
                sendToScouts={sendToScouts}
                onSendToScoutsChange={setSendToScouts}
                sendToScoutsDisabledReason={steerDisabledReason}
                skillName={skillName}
                onSkillNameChange={setSkillName}
                targetOptions={targetOptions}
                targetOptionsLoading={scoutConfigsLoading}
                saving={savingNote}
                onCancel={onClose}
                onSubmit={() => void submit()}
            />
        )
    }

    return (
        <div className="flex flex-col gap-2 rounded border border-primary bg-surface-primary p-2">
            <ScoutNoteComposer maxLength={maxLength} placeholder={placeholder} onChange={setText} />
            <div className="flex flex-wrap items-center gap-2">
                <LemonCheckbox
                    size="small"
                    checked={sendToScouts}
                    disabledReason={steerDisabledReason}
                    onChange={setSendToScouts}
                    label="Also send to the scouts"
                    data-attr="inbox-report-note-send-to-scouts"
                />
                {sendToScouts && (
                    <LemonSelect
                        size="small"
                        value={skillName}
                        options={targetOptions}
                        loading={scoutConfigsLoading}
                        onChange={setSkillName}
                        data-attr="inbox-report-note-target"
                    />
                )}
                <span className="flex-1" />
                <LemonButton
                    size="small"
                    type="tertiary"
                    onClick={onClose}
                    disabledReason={savingNote ? 'Saving' : undefined}
                >
                    Cancel
                </LemonButton>
                <LemonButton
                    size="small"
                    type="primary"
                    loading={savingNote}
                    disabledReason={text.trim() ? undefined : 'Write a note first'}
                    onClick={() => void submit()}
                    data-attr="inbox-report-note-submit"
                >
                    Add note
                </LemonButton>
            </div>
            {sendToScouts && (
                <span className="text-xs text-tertiary">
                    Scouts read the note at the start of every run until you retire it.
                </span>
            )}
        </div>
    )
}

export function ReportNoteComposer({ report }: { report: SignalReport }): JSX.Element {
    const [open, setOpen] = useState(false)
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')
    if (open) {
        return <OpenComposer report={report} onClose={() => setOpen(false)} />
    }
    if (todayRailNav) {
        return <QuillReportNoteAddButton onClick={() => setOpen(true)} />
    }
    return (
        <LemonInput
            size="small"
            className="px-2"
            placeholder="Add a note…"
            onFocus={() => setOpen(true)}
            aria-label="Add a note about this report"
            data-attr="inbox-report-note-box"
        />
    )
}
