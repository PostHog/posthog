import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconPencil, IconTrash } from '@posthog/icons'
import { LemonButton, LemonDialog, LemonTag, LemonTextArea, Tooltip } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { getAccessControlDisabledReason } from 'lib/utils/accessControlUtils'
import { pluralize } from 'lib/utils/strings'

import { AccessControlLevel, AccessControlResourceType } from '~/types'

import type { ScoutNoteApi } from 'products/signals/frontend/generated/api.schemas'

import {
    isDirectScoutNote,
    NOTES_FETCH_LIMIT,
    scoutNoteOriginLabel,
    scoutNotesLogic,
} from '../../../logics/scoutNotesLogic'
import { ScoutNoteContent } from './ScoutNoteContent'

/** Bounded by the create serializer; mirrored here so the dialog can say so before a failed request. */
const NOTE_MAX_CHARS = 10000

/**
 * Controlled so LemonTextArea's counter has a value to count; an uncontrolled textarea reports
 * 0 / max no matter what is typed.
 */
function NoteComposer({ onChange }: { onChange: (content: string) => void }): JSX.Element {
    const [content, setContent] = useState('')
    return (
        <LemonTextArea
            autoFocus
            value={content}
            maxLength={NOTE_MAX_CHARS}
            placeholder="e.g. we shipped a new checkout on Tuesday, watch conversion closely"
            onChange={(value) => {
                setContent(value)
                onChange(value)
            }}
        />
    )
}

/** Notes are written and retired through the skill, so the same editor access gates both. */
function noteWriteDisabledReason(): string | undefined {
    return getAccessControlDisabledReason(AccessControlResourceType.LlmSkill, AccessControlLevel.Editor) ?? undefined
}

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
                <NoteComposer
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
    const { savingNote } = useValues(logic)
    const disabledReason = noteWriteDisabledReason()

    return (
        <LemonButton
            type={type}
            size={size}
            icon={<IconPencil />}
            loading={savingNote}
            disabledReason={disabledReason ?? (savingNote ? 'Saving the note' : undefined)}
            onClick={() =>
                LeaveNoteDialog({
                    skillName,
                    onSubmit: async (content) => {
                        await logic.asyncActions.createNote(content)
                        return !logic.values.lastSaveFailed
                    },
                })
            }
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
    const { scoutNotes, fleetWideNotes, notesLoading, notesLoadFailed, notesCapped } = useValues(logic)
    const { deleteNote, loadNotes } = useActions(logic)
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
            ) : notesLoadFailed && scoutNotes.length === 0 ? (
                <div className="flex flex-col items-center gap-2 rounded border border-danger bg-danger-highlight px-4 py-6 text-center text-sm text-danger">
                    <span>Couldn't load the notes.</span>
                    <LemonButton size="xsmall" type="secondary" onClick={() => loadNotes()}>
                        Try again
                    </LemonButton>
                </div>
            ) : scoutNotes.length === 0 ? (
                <div className="rounded border border-dashed border-primary bg-surface-primary px-4 py-6 text-center text-sm text-muted">
                    Nothing yet. Leave a note to steer what this scout looks at, or dismiss one of its reports with a
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
                    {showAll && notesCapped && (
                        <span className="border-t border-primary px-3 py-2 text-[11px] text-muted">
                            Showing the newest {NOTES_FETCH_LIMIT} notes.
                        </span>
                    )}
                </div>
            )}

            <span className="text-xs text-muted">
                New notes are picked up on the next run and folded into what it has learned. Delete a note once it has
                done its job.
                {otherFleetNotes.length > 0 &&
                    ` ${pluralize(otherFleetNotes.length, 'note')} addressed to every scout applies here too.`}
            </span>
        </div>
    )
}

function ScoutNoteRow({ note, onDelete }: { note: ScoutNoteApi; onDelete: () => void }): JSX.Element {
    const direct = isDirectScoutNote(note)
    const disabledReason = noteWriteDisabledReason()

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
                <ScoutNoteContent content={note.content} />
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
