import { dayjs } from 'lib/dayjs'
import { humanFriendlyDuration } from 'lib/utils/durations'

import type { ModelChoiceApi, TaskRunDetailDTOApi } from 'products/tasks/frontend/generated/api.schemas'

import { getEffortLabel, getModelLabel } from '../../../utils/composerModels'

export type TaskRunMetadataField =
    | { label: 'Created' | 'Completed'; kind: 'time'; value: string }
    | { label: 'Duration' | 'Model'; kind: 'text'; value: string }

export function getTaskRunMetadataFields(
    run: TaskRunDetailDTOApi,
    catalogue: ModelChoiceApi[]
): TaskRunMetadataField[] {
    const fields: TaskRunMetadataField[] = []
    if (run.created_at) {
        fields.push({ label: 'Created', kind: 'time', value: run.created_at })
    }
    if (run.completed_at) {
        fields.push({ label: 'Completed', kind: 'time', value: run.completed_at })
    }
    // An import run holds a chat copied from the legacy runtime and never executed, so it has no duration.
    if (run.completed_at && run.created_at && !run.state?.imported_from) {
        fields.push({
            label: 'Duration',
            kind: 'text',
            value: humanFriendlyDuration(dayjs(run.completed_at).diff(run.created_at, 'second')),
        })
    }
    // What the run actually launched with, not what the composer currently has picked — a read-only
    // viewer has no pickers to read, and on a resumed task the two can differ.
    if (run.model) {
        fields.push({
            label: 'Model',
            kind: 'text',
            value:
                getModelLabel(catalogue, run.model) +
                (run.reasoning_effort ? ` · ${getEffortLabel(run.reasoning_effort)}` : ''),
        })
    }
    return fields
}
