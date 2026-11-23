import { useActions, useValues } from 'kea'
import { useId } from 'react'

import { Button, Field, FieldDescription, FieldLabel, Textarea } from '@posthog/quill'

import { RUN_NOTE_MAX_CHARS, runNoteSubmitDisabledReason } from '../../../logics/scoutDetailActionsLogic'
import { scoutFleetLogic } from '../../../logics/scoutFleetLogic'

/** The draft lives in the logic, so a failed run keeps the note for a retry. */
export function QuillScoutRunNoteForm({ configId }: { configId: string }): JSX.Element {
    const { manualRunScoutIds, runNoteDrafts } = useValues(scoutFleetLogic)
    const { runScoutNow, setRunNoteDraft } = useActions(scoutFleetLogic)
    const running = manualRunScoutIds.includes(configId)
    const note = runNoteDrafts[configId] ?? ''
    const textareaId = useId()

    return (
        <div className="flex w-80 max-w-full flex-col gap-2">
            <Field>
                <FieldLabel htmlFor={textareaId}>Run with a note</FieldLabel>
                <FieldDescription>
                    The note steers this run only. To steer every later run, use Tell it something.
                </FieldDescription>
                <Textarea
                    id={textareaId}
                    autoFocus
                    value={note}
                    maxLength={RUN_NOTE_MAX_CHARS}
                    placeholder="e.g. focus on the checkout regression"
                    onChange={(event) => setRunNoteDraft(configId, event.target.value)}
                />
            </Field>
            <div className="flex justify-end">
                <Button
                    variant="primary"
                    loading={running}
                    disabledReason={runNoteSubmitDisabledReason(running, note)}
                    onClick={() => runScoutNow(configId, note)}
                >
                    Run
                </Button>
            </div>
        </div>
    )
}
