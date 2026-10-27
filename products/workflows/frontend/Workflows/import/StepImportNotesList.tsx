import { useValues } from 'kea'

import { workflowImportNotesLogic } from './workflowImportNotesLogic'

export function StepImportNotesList({
    workflowId,
    stepId,
}: {
    workflowId: string
    stepId: string
}): JSX.Element | null {
    const { notesByStepId } = useValues(workflowImportNotesLogic({ id: workflowId }))
    const notes = notesByStepId[stepId]
    if (!notes?.length) {
        return null
    }
    return (
        <div className="flex flex-col gap-1 text-xs" data-attr="workflow-step-import-notes-list">
            <div className="font-semibold">From the Customer.io import</div>
            <ul className="m-0 list-disc pl-4">
                {notes.map((note, index) => (
                    <li key={index}>{note.message}</li>
                ))}
            </ul>
        </div>
    )
}
