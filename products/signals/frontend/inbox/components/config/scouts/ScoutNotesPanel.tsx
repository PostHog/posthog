import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconPencil, IconTrash } from '@posthog/icons'
import { LemonButton, LemonDialog, LemonTag, LemonTextArea, Tooltip } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'
import { pluralize } from 'lib/utils/strings'

import type { ScoutNoteApi } from 'products/signals/frontend/generated/api.schemas'

import { isDirectScoutNote, scoutNoteOriginLabel, scoutNotesLogic } from '../../../logics/scoutNotesLogic'

/** Bounded by the create serializer; mirrored here so the dialog can say so before a failed request. */
const NOTE_MAX_CHARS = 10000

function LeaveNoteDialog({ skillName, onSubmit }: { skillName: string; onSubmit: (content: string) => void }): void {
    let content = ''
    LemonDialog.open({
        title: skillName ? 'Tell this scout something' : 'Tell every scout something',
        description: skillName
            ? 'It reads this at the start of every run, alongside what it has already learned.'
            : 'Every scout on this project reads this at the start of every run.',
        content: (
            <LemonTextArea
                autoFocus
                maxLength={NOTE_MAX_CHARS}
                placeholder="e.g. we shipped a new checkout on Tuesday, watch conversion closely"
                onChange={(value) => {
                    content = value
                }}
            />
        ),
        primaryButton: {
            children: 'Leave note',
            onClick: () => {
                const trimmed = content.trim()
                if (trimmed) {
                    onSubmit(trimmed)
                }
            },
        },
        secondaryButton: { children: 'Cancel' },
    })
}

/** Opens the note composer. Sits in the scout page header and above the notes panel. */
export function LeaveScoutNoteButton({
    skillName,
    size = 'small',
    type = 'secondary',
}: {
    skillName: string
    size?: 'xsmall' | 'small'
    type?: 'primary' | 'secondary' | 'tertiary'
}): JSX.Element {
    const logic = scoutNotesLogic({ skillName })
    const { createNote } = useActions(logic)
    const { savingNote } = useValues(logic)

    return (
        <LemonButton
            type={type}
            size={size}
            icon={<IconPencil />}
            loading={savingNote}
            disabledReason={savingNote ? 'Saving the note' : undefined}
            onClick={() => LeaveNoteDialog({ skillName, onSubmit: createNote })}
        >
            {skillName ? 'Tell it something' : 'Tell them all something'}
        </LemonButton>
    )
}

/**
 * What the team has told this scout: notes someone typed, plus the ones the inbox forwarded when a
 * report was dismissed, discussed, or rated. Without this the loop is invisible — people teach the
 * fleet by judging its reports and never see that it landed.
 */
export function ScoutNotesPanel({ skillName }: { skillName: string }): JSX.Element {
    const logic = scoutNotesLogic({ skillName })
    const { scoutNotes, fleetWideNotes, notesLoading } = useValues(logic)
    const { deleteNote } = useActions(logic)
    const [showAll, setShowAll] = useState(false)

    const visible = showAll ? scoutNotes : scoutNotes.slice(0, 4)
    const otherFleetNotes = skillName ? fleetWideNotes.filter((note) => !scoutNotes.includes(note)) : []

    return (
        <div className="flex flex-col gap-2">
            <div className="flex items-center gap-2">
                <span className="text-xs font-medium uppercase tracking-wide text-default">What you've told it</span>
                <span className="flex-1" />
                <LeaveScoutNoteButton skillName={skillName} size="xsmall" />
            </div>

            {notesLoading && scoutNotes.length === 0 ? (
                <div className="rounded border border-primary bg-surface-primary px-4 py-6 text-center text-sm text-muted">
                    Loading notes…
                </div>
            ) : scoutNotes.length === 0 ? (
                <div className="rounded border border-dashed border-primary bg-surface-primary px-4 py-6 text-center text-sm text-muted">
                    Nothing yet. Leave a note to steer what this scout looks at — or dismiss one of its reports with a
                    reason, and that reaches it too.
                </div>
            ) : (
                <div className="flex flex-col rounded border border-primary bg-surface-primary">
                    {visible.map((note) => (
                        <ScoutNoteRow key={note.id} note={note} onDelete={() => deleteNote(note.id)} />
                    ))}
                    {scoutNotes.length > visible.length && (
                        <div className="border-t border-primary px-3 py-2">
                            <LemonButton size="xsmall" type="tertiary" onClick={() => setShowAll(true)}>
                                Show all {pluralize(scoutNotes.length, 'note')}
                            </LemonButton>
                        </div>
                    )}
                </div>
            )}

            <span className="text-xs text-muted">
                Read at the start of every run.
                {otherFleetNotes.length > 0 &&
                    ` ${pluralize(otherFleetNotes.length, 'note')} addressed to every scout applies here too.`}
            </span>
        </div>
    )
}

function ScoutNoteRow({ note, onDelete }: { note: ScoutNoteApi; onDelete: () => void }): JSX.Element {
    const direct = isDirectScoutNote(note)

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
                    {note.created_at && <TZLabel time={note.created_at} />}
                    {note.expires_at && (
                        <Tooltip title="This note retires itself, so time-boxed steering doesn't linger">
                            <span>
                                expires <TZLabel time={note.expires_at} />
                            </span>
                        </Tooltip>
                    )}
                </div>
                <LemonMarkdown className="text-xs text-secondary">{note.content}</LemonMarkdown>
            </div>
            {/* Only a note someone left here is retired here. A derived one is a record of what
                happened in the inbox, and deleting it would rewrite that. */}
            {direct && (
                <Tooltip title="Retire this note">
                    <LemonButton
                        size="xsmall"
                        icon={<IconTrash />}
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
