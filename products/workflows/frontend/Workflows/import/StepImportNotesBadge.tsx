import { useValues } from 'kea'

import { IconInfo } from '@posthog/icons'

import { cn } from 'lib/utils/css-classes'

import { workflowImportNotesLogic } from './workflowImportNotesLogic'

export function StepImportNotesBadge({
    workflowId,
    stepId,
    className,
}: {
    workflowId: string
    stepId: string
    className?: string
}): JSX.Element | null {
    const { notesByStepId } = useValues(workflowImportNotesLogic({ id: workflowId }))
    const notes = notesByStepId[stepId]
    if (!notes?.length) {
        return null
    }
    const needsInput = notes.some((note) => note.level === 'needs_input')
    return (
        <span
            className={cn(
                'absolute flex items-center justify-center rounded-full bg-surface-primary',
                needsInput ? 'text-warning' : 'text-secondary',
                className
            )}
            data-attr="workflow-step-import-notes"
            aria-label={`${notes.length} import ${notes.length === 1 ? 'note' : 'notes'}`}
        >
            <IconInfo className="text-lg" />
        </span>
    )
}
