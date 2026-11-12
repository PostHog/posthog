import { useActions, useValues } from 'kea'

import { LemonButton, LemonDialog, LemonTag, Tooltip } from '@posthog/lemon-ui'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'

import { reportNotesLogic } from '../../logics/reportNotesLogic'
import { scoutNoteWriteDisabledReason } from '../../logics/scoutNotesLogic'
import { QuillScoutNoteStatus } from './QuillScoutNoteStatus'

/** Whether the scouts still read a note sent from this report, and the control to stop them. */
export function ScoutNoteStatus({
    reportId,
    scoutNoteId,
}: {
    reportId: string
    scoutNoteId: string
}): JSX.Element | null {
    const logic = reportNotesLogic({ reportId })
    const { activeNoteIds, notesResolved, notesLoadFailed, notesCapped } = useValues(logic)
    const { retireNote } = useActions(logic)
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')

    // Unknown until the notes load. A failed load says nothing rather than claim the note is retired,
    // and neither does a capped read, which can leave an older active note out of what it returned.
    if (!notesResolved || notesLoadFailed) {
        return null
    }
    const active = activeNoteIds.has(scoutNoteId)
    if (!active && notesCapped) {
        return null
    }
    if (todayRailNav) {
        return (
            <QuillScoutNoteStatus
                active={active}
                retireDisabledReason={scoutNoteWriteDisabledReason()}
                onRetire={() => retireNote(scoutNoteId)}
            />
        )
    }
    if (!active) {
        return (
            <Tooltip title="Retired or expired. Scouts no longer read it.">
                <LemonTag size="small" type="muted">
                    Inactive
                </LemonTag>
            </Tooltip>
        )
    }
    return (
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
                        description: 'Scouts stop reading it from their next run onward. It stays on the report.',
                        primaryButton: {
                            children: 'Retire',
                            status: 'danger',
                            onClick: () => retireNote(scoutNoteId),
                        },
                        secondaryButton: { children: 'Cancel' },
                    })
                }
                data-attr="inbox-report-note-retire"
            >
                Retire
            </LemonButton>
        </>
    )
}
