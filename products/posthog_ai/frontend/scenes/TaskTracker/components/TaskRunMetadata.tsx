import { useValues } from 'kea'

import { TZLabel } from 'lib/components/TZLabel'
import { dayjs } from 'lib/dayjs'
import { humanFriendlyDuration } from 'lib/utils/durations'

import { modelCatalogueLogic } from '../../../logics/modelCatalogueLogic'
import { TaskRun } from '../../../types/taskTypes'
import { getEffortLabel, getModelLabel } from '../../../utils/composerModels'

/** Created / completed / duration / model row shown above the run log for the selected run. */
export function TaskRunMetadata({ selectedRun }: { selectedRun: TaskRun }): JSX.Element {
    const { catalogue } = useValues(modelCatalogueLogic)

    return (
        <div className="items-center gap-4 text-xs text-muted hidden lg:flex">
            <dl className="inline-flex gap-1 items-center">
                <dt className="m-0">Created:</dt>
                <dd className="m-0 inline-flex items-center">
                    <TZLabel time={selectedRun.created_at} showSeconds />
                </dd>
            </dl>
            {selectedRun.completed_at && (
                <dl className="inline-flex gap-1 items-center">
                    <dt className="m-0">Completed:</dt>
                    <dd className="m-0 inline-flex items-center">
                        <TZLabel time={selectedRun.completed_at} showSeconds />
                    </dd>
                </dl>
            )}
            {selectedRun.completed_at && (
                <dl className="inline-flex gap-1 items-center">
                    <dt className="m-0">Duration:</dt>
                    <dd className="m-0 inline-flex items-center">
                        {humanFriendlyDuration(dayjs(selectedRun.completed_at).diff(selectedRun.created_at, 'second'))}
                    </dd>
                </dl>
            )}
            {/* What the run actually launched with, not what the composer currently has picked — a read-only
            viewer has no pickers to read, and on a resumed task the two can differ. */}
            {selectedRun.model && (
                <dl className="inline-flex gap-1 items-center">
                    <dt className="m-0">Model:</dt>
                    <dd className="m-0 inline-flex items-center">
                        {getModelLabel(catalogue, selectedRun.model)}
                        {selectedRun.reasoning_effort && ` · ${getEffortLabel(selectedRun.reasoning_effort)}`}
                    </dd>
                </dl>
            )}
        </div>
    )
}
