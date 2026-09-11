import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconPencil, IconRefresh } from '@posthog/icons'
import { LemonButton, LemonDialog, LemonTextArea, Tooltip } from '@posthog/lemon-ui'

import { getAccessControlDisabledReason } from 'lib/utils/accessControlUtils'

import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { scoutFleetLogic } from '../../../logics/scoutFleetLogic'

/** Bounded by the run endpoint's serializer; mirrored here so the dialog says so before a failed request. */
const RUN_NOTE_MAX_CHARS = 1000

/**
 * Controlled so LemonTextArea's counter has a value to count; an uncontrolled textarea reports
 * 0 / max no matter what is typed.
 */
function RunNoteComposer({ onChange }: { onChange: (note: string) => void }): JSX.Element {
    const [note, setNote] = useState('')
    return (
        <LemonTextArea
            autoFocus
            value={note}
            maxLength={RUN_NOTE_MAX_CHARS}
            placeholder="e.g. focus on the checkout regression from this morning"
            onChange={(value) => {
                setNote(value)
                onChange(value)
            }}
        />
    )
}

function RunWithNoteDialog({ onSubmit }: { onSubmit: (note: string) => void }): void {
    let note = ''
    LemonDialog.open({
        title: 'Run with a note',
        description:
            'The scout reads this on this run only. Nothing is left behind, so the next scheduled run is unaffected.',
        content: () => (
            <RunNoteComposer
                onChange={(value) => {
                    note = value
                }}
            />
        ),
        primaryButton: {
            children: 'Run now',
            onClick: () => {
                const trimmed = note.trim()
                if (trimmed) {
                    onSubmit(trimmed)
                }
            },
        },
        secondaryButton: { children: 'Cancel' },
    })
}

/**
 * Dispatches a run outside the schedule. The side action attaches a one-off note to that run, which
 * is the alternative to leaving a durable note and remembering to delete it afterwards. A note is
 * read verbatim by the agent, so it takes the same skill-editor access as leaving one — the plain
 * run stays open to everyone who can run a scout.
 */
export function ScoutRunNowButton({ configId }: { configId: string }): JSX.Element {
    const { manualRunScoutIds } = useValues(scoutFleetLogic)
    const { runScoutNow } = useActions(scoutFleetLogic)

    const running = manualRunScoutIds.includes(configId)
    const noteDisabledReason =
        getAccessControlDisabledReason(AccessControlResourceType.LlmSkill, AccessControlLevel.Editor) ?? undefined

    return (
        <Tooltip title="Dispatch a run now, outside the schedule. Counts against the project's daily run budget.">
            <LemonButton
                type="secondary"
                size="small"
                icon={<IconRefresh />}
                loading={running}
                disabledReason={running ? 'Starting a run' : undefined}
                onClick={() => runScoutNow(configId)}
                data-attr="scout-run-now"
                sideAction={{
                    icon: <IconPencil />,
                    tooltip: 'Run with a one-off note',
                    disabledReason: noteDisabledReason ?? (running ? 'Starting a run' : undefined),
                    onClick: () => RunWithNoteDialog({ onSubmit: (note) => runScoutNow(configId, note) }),
                    'data-attr': 'scout-run-now-with-note',
                }}
            >
                Run now
            </LemonButton>
        </Tooltip>
    )
}
