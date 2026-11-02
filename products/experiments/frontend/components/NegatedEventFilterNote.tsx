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
            These filters remove individual events, not {units}. {capitalizeFirstLetter(units)} still count as long as
            one of their events of this type passes the filters.
            {!isLaunched(experiment) &&
                ` To keep ${units} out of the experiment, exclude them in the feature flag's release conditions.`}
        </div>
    )
}
