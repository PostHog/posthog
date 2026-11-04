import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { LemonBanner } from '@posthog/lemon-ui'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'

import { WorkflowImportNoteApi } from 'products/workflows/frontend/generated/api.schemas'

import { workflowImportNotesLogic } from './workflowImportNotesLogic'

const LEVEL_HEADINGS: Record<WorkflowImportNoteApi['level'], string> = {
    needs_input: 'Needs your input before you enable it',
    approximated: 'Works differently in PostHog',
    unsupported: 'Left out',
}
const LEVEL_ORDER: WorkflowImportNoteApi['level'][] = ['needs_input', 'approximated', 'unsupported']

export function WorkflowImportNotesBanner({ id }: { id: string }): JSX.Element | null {
    const { importRecord, loadFailed } = useValues(workflowImportNotesLogic({ id }))
    const { loadImportRecord } = useActions(workflowImportNotesLogic({ id }))
    const importEnabled = useFeatureFlag('WORKFLOWS_CUSTOMERIO_IMPORT')
    const [expanded, setExpanded] = useState(false)

    // Most workflows were never imported, so a failed lookup only warns people who can import.
    if (loadFailed && importEnabled) {
        return (
            <div className="shrink-0" data-attr="workflow-import-notes-banner">
                <LemonBanner
                    type="warning"
                    action={{
                        children: 'Retry',
                        onClick: loadImportRecord,
                        'data-attr': 'workflow-import-notes-retry',
                    }}
                >
                    The import notes for this workflow didn't load. If it was imported from Customer.io, check them
                    before you enable it.
                </LemonBanner>
            </div>
        )
    }
    if (!importRecord) {
        return null
    }
    const notes = importRecord.notes
    const needsInput = notes.filter((note) => note.level === 'needs_input').length
    const summary = notes.length
        ? needsInput
            ? `${needsInput} ${needsInput === 1 ? 'setting needs' : 'settings need'} your input before you enable it.`
            : 'Review the notes before you enable it.'
        : 'Everything carried over.'

    return (
        <div className="shrink-0" data-attr="workflow-import-notes-banner">
            <LemonBanner
                type={needsInput ? 'warning' : 'info'}
                action={
                    notes.length
                        ? {
                              children: expanded ? 'Hide notes' : 'Show notes',
                              onClick: () => setExpanded(!expanded),
                              'data-attr': 'workflow-import-notes-toggle',
                          }
                        : undefined
                }
            >
                Imported from Customer.io ({importRecord.source_name || importRecord.source_id}). {summary}
                {expanded && (
                    <div className="mt-2 flex flex-col gap-2">
                        {LEVEL_ORDER.map((level) => {
                            const levelNotes = notes.filter((note) => note.level === level)
                            if (!levelNotes.length) {
                                return null
                            }
                            return (
                                <div key={level}>
                                    <div className="font-semibold">{LEVEL_HEADINGS[level]}</div>
                                    <ul className="list-disc pl-5">
                                        {levelNotes.map((note, index) => (
                                            <li key={index}>
                                                {note.step_name ? <strong>{note.step_name}: </strong> : null}
                                                {note.message}
                                            </li>
                                        ))}
                                    </ul>
                                </div>
                            )
                        })}
                    </div>
                )}
            </LemonBanner>
        </div>
    )
}
