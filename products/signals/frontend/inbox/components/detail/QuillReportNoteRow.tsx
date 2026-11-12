import { ProfilePicture } from '@posthog/lemon-ui'
import { Badge, Text } from '@posthog/quill'

import { TZLabel } from 'lib/components/TZLabel'
import { TodayMarkedText } from 'scenes/project-homepage/today/TodayMarkedText'

import { SignalReportArtefact } from '../../types'
import { ScoutNoteLeftContent } from './artefactTypes'
import { ScoutNoteAudience } from './ScoutNoteAudience'
import { ScoutNoteStatus } from './ScoutNoteStatus'

export function QuillReportNoteRow({
    reportId,
    note,
    author,
    text,
    scoutNote,
}: {
    reportId: string
    note: SignalReportArtefact
    author: string
    text: string
    scoutNote: ScoutNoteLeftContent | null
}): JSX.Element {
    return (
        <div className="flex gap-2.5">
            <ProfilePicture user={note.created_by ?? { first_name: author }} size="sm" className="mt-0.5" />
            <div className="flex min-w-0 flex-1 flex-col">
                <Text size="sm" variant="muted" render={<div />} className="flex flex-wrap items-center gap-1.5">
                    <span className="font-semibold text-foreground">{author}</span>
                    <span aria-hidden>·</span>
                    <TZLabel time={note.created_at} />
                    {scoutNote && (
                        <>
                            <Badge>
                                <ScoutNoteAudience reportId={reportId} skillName={scoutNote.skill_name} />
                            </Badge>
                            <ScoutNoteStatus reportId={reportId} scoutNoteId={scoutNote.scout_note_id} />
                        </>
                    )}
                </Text>
                <Text size="sm" render={<p />} className="leading-relaxed whitespace-pre-wrap">
                    <TodayMarkedText markdown={text} marked={[]} keyClauses={[]} reportId={reportId} plainLinks />
                </Text>
            </div>
        </div>
    )
}
