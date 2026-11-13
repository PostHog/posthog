import { LemonTag, ProfilePicture } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'

import { SignalReportArtefact } from '../../types'
import { artefactAttributionLabel, NoteContent, ScoutNoteLeftContent } from './artefactTypes'
import { ScoutNoteAudience } from './ScoutNoteAudience'
import { ScoutNoteStatus } from './ScoutNoteStatus'

export function ReportNoteRow({ reportId, note }: { reportId: string; note: SignalReportArtefact }): JSX.Element {
    const scoutNote = note.type === 'scout_note_left' ? (note.content as ScoutNoteLeftContent) : null
    const text = scoutNote ? scoutNote.note : (note.content as NoteContent).note
    const author = artefactAttributionLabel(note) ?? 'Someone'

    return (
        <div className="flex gap-2.5 border-b border-primary px-3 py-2.5 last:border-b-0">
            <ProfilePicture user={note.created_by ?? { first_name: author }} size="md" />
            <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center gap-1.5 text-xs">
                    <span className="font-medium text-default">{author}</span>
                    <TZLabel time={note.created_at} className="text-tertiary" />
                    {scoutNote && (
                        <>
                            <LemonTag size="small" type="option">
                                <ScoutNoteAudience reportId={reportId} skillName={scoutNote.skill_name} />
                            </LemonTag>
                            <ScoutNoteStatus reportId={reportId} scoutNoteId={scoutNote.scout_note_id} />
                        </>
                    )}
                </div>
                <LemonMarkdown className="mt-1 text-sm text-default" disableImages>
                    {text}
                </LemonMarkdown>
            </div>
        </div>
    )
}
