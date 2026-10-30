import { IconTrash } from '@posthog/icons'
import { LemonButton, LemonDialog, LemonTag, Tooltip } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'

import type { ScoutNoteApi } from 'products/signals/frontend/generated/api.schemas'

import { isDirectScoutNote, scoutNoteOriginLabel, scoutNoteWriteDisabledReason } from '../../../logics/scoutNotesLogic'
import { ScoutNoteContent } from './ScoutNoteContent'

export function ScoutNoteRow({
    note,
    content,
    audience,
    onDelete,
}: {
    note: ScoutNoteApi
    content: string
    /** Who reads the note, for lists that mix notes addressed to different scouts. */
    audience?: string
    onDelete: () => void
}): JSX.Element {
    const direct = isDirectScoutNote(note)
    const disabledReason = scoutNoteWriteDisabledReason()

    return (
        <div className="flex gap-3 border-b border-primary px-3 py-2.5 last:border-b-0">
            <div className="flex min-w-0 flex-1 flex-col gap-1">
                <div className="flex flex-wrap items-center gap-2 text-[11px] text-muted">
                    {direct ? (
                        <span className="font-medium text-secondary">{note.created_by_name ?? 'Someone'}</span>
                    ) : (
                        <LemonTag size="small" type="option">
                            {scoutNoteOriginLabel(note.origin)}
                        </LemonTag>
                    )}
                    {audience && <span>{audience}</span>}
                    {note.created_at && <TZLabel time={note.created_at} />}
                    {note.expires_at && (
                        <Tooltip title="This note retires itself, so time-boxed steering doesn't linger">
                            <span>
                                expires <TZLabel time={note.expires_at} />
                            </span>
                        </Tooltip>
                    )}
                </div>
                <ScoutNoteContent content={content} />
            </div>
            {/* Only a note someone left here is retired here. A derived one is a record of what
                happened in the inbox, and deleting it would rewrite that. */}
            {direct && (
                <Tooltip title="Retire this note">
                    <LemonButton
                        size="xsmall"
                        icon={<IconTrash />}
                        disabledReason={disabledReason}
                        onClick={() =>
                            LemonDialog.open({
                                title: 'Retire this note?',
                                description: 'Scouts stop reading it from their next run onward.',
                                primaryButton: { children: 'Retire', status: 'danger', onClick: onDelete },
                                secondaryButton: { children: 'Cancel' },
                            })
                        }
                        aria-label="Retire note"
                    />
                </Tooltip>
            )}
        </div>
    )
}
