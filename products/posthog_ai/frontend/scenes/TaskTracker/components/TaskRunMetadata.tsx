import { useValues } from 'kea'

import { TZLabel } from 'lib/components/TZLabel'

import type { TaskRunDetailDTOApi } from 'products/tasks/frontend/generated/api.schemas'

import { modelCatalogueLogic } from '../../../logics/modelCatalogueLogic'
import { getTaskRunMetadataFields } from './taskRunMetadataFields'

/** Created / completed / duration / model row shown above the run log for the selected run. */
export function TaskRunMetadata({ selectedRun }: { selectedRun: TaskRunDetailDTOApi }): JSX.Element {
    const { catalogue } = useValues(modelCatalogueLogic)

    return (
        <div className="items-center gap-4 text-xs text-muted hidden lg:flex">
            {getTaskRunMetadataFields(selectedRun, catalogue).map((field) => (
                <dl key={field.label} className="inline-flex gap-1 items-center">
                    <dt className="m-0">{field.label}:</dt>
                    <dd className="m-0 inline-flex items-center">
                        {field.kind === 'time' ? <TZLabel time={field.value} showSeconds /> : field.value}
                    </dd>
                </dl>
            ))}
        </div>
    )
}
