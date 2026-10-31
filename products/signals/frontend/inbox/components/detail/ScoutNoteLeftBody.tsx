import { useActions, useValues } from 'kea'

import { LemonButton, LemonDialog, LemonTag, Tooltip } from '@posthog/lemon-ui'

import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'

import { reportNoteAudience, reportNotesLogic } from '../../logics/reportNotesLogic'
import { scoutNoteWriteDisabledReason } from '../../logics/scoutNotesLogic'
import { ScoutNoteLeftContent } from './artefactTypes'

/**
 * A note someone sent to the scouts from this report. The entry is history and outlives the note, so
 * it also says whether the scouts still read it and offers to retire it while they do.
 */
export function ScoutNoteLeftBody({
    reportId,
    content,
}: {
    reportId: string
    content: ScoutNoteLeftContent
}): JSX.Element {
    const logic = reportNotesLogic({ reportId })
    const { activeNoteIds, notesResolved, notesLoadFailed, notesCapped, scoutNamesBySkill } = useValues(logic)
    const { retireNote } = useActions(logic)
    // Unknown until the notes load. A failed load says nothing rather than claim the note is retired,
    // and neither does a capped read, which can leave an older active note out of what it returned.
    const read = notesResolved && !notesLoadFailed
    const status = !read ? null : activeNoteIds.has(content.scout_note_id) ? true : notesCapped ? null : false

    return (
        <div className="w-full">
            <div className="mb-1 flex flex-wrap items-center gap-2 text-xs text-tertiary">
                <span>{reportNoteAudience(content.skill_name, scoutNamesBySkill)}</span>
                {status === true && (
                    <>
                        <LemonTag size="small" type="success">
                            Active
                        </LemonTag>
                        <LemonButton
                            size="xsmall"
                            type="tertiary"
                            disabledReason={scoutNoteWriteDisabledReason()}
                            onClick={() =>
                                LemonDialog.open({
                                    title: 'Retire this note?',
                                    description:
                                        'Scouts stop reading it from their next run onward. It stays in the activity log.',
                                    primaryButton: {
                                        children: 'Retire',
                                        status: 'danger',
                                        onClick: () => retireNote(content.scout_note_id),
                                    },
                                    secondaryButton: { children: 'Cancel' },
                                })
                            }
                            data-attr="inbox-report-note-retire"
                        >
                            Retire
                        </LemonButton>
                    </>
                )}
                {status === false && (
                    <Tooltip title="Retired or expired. Scouts no longer read it.">
                        <LemonTag size="small" type="muted">
                            Inactive
                        </LemonTag>
                    </Tooltip>
                )}
            </div>
            <LemonMarkdown className="text-xs text-secondary leading-normal" disableImages>
                {content.note}
            </LemonMarkdown>
        </div>
    )
}
