import { useValues } from 'kea'

import { capitalizeFirstLetter } from 'lib/utils/strings'
import { hasNegatedEventFilter } from 'scenes/experiments/exposureContract'

import { groupsModel } from '~/models/groupsModel'
import type { ExperimentExposureConfig } from '~/queries/schema/schema-general'
import type { Experiment } from '~/types'

import { isLaunched } from '../experimentStatus'

export function NegatedEventFilterNote({
    config,
    experiment,
}: {
    config: ExperimentExposureConfig | undefined
    experiment: Pick<Experiment, 'status' | 'start_date' | 'end_date' | 'feature_flag'>
}): JSX.Element | null {
    const { aggregationLabel } = useValues(groupsModel)
    const groupTypeIndex = experiment.feature_flag?.filters?.aggregation_group_type_index
    if (!hasNegatedEventFilter(config, groupTypeIndex)) {
        return null
    }
    const units = aggregationLabel(groupTypeIndex, true).plural
    return (
        <div className="text-xs text-muted mt-1">
            A filter on an event property applies to each event. {capitalizeFirstLetter(units)} with a left-out event
            still count if another of their events passes the filter.
            {!isLaunched(experiment) &&
                ` To keep ${units} out of the experiment, leave them out in the feature flag's release conditions.`}
        </div>
    )
}
