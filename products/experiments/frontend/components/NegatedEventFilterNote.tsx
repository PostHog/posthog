import { useValues } from 'kea'

import { capitalizeFirstLetter } from 'lib/utils/strings'
import { hasNegatedEventFilter } from 'scenes/experiments/exposureContract'
import { teamLogic } from 'scenes/teamLogic'

import { groupsModel } from '~/models/groupsModel'
import type { ExperimentExposureConfig } from '~/queries/schema/schema-general'

export function NegatedEventFilterNote({
    config,
    launched,
    groupTypeIndex,
}: {
    config: ExperimentExposureConfig | undefined
    launched: boolean
    /** The aggregation group of the experiment's flag, or null when the flag counts persons. */
    groupTypeIndex: number | null | undefined
}): JSX.Element | null {
    const { aggregationLabel } = useValues(groupsModel)
    const { currentTeam } = useValues(teamLogic)
    const personsOnEventsMode =
        currentTeam?.modifiers?.personsOnEventsMode ?? currentTeam?.default_modifiers?.personsOnEventsMode
    if (!hasNegatedEventFilter(config, groupTypeIndex, personsOnEventsMode)) {
        return null
    }
    const units = aggregationLabel(groupTypeIndex, true).plural
    return (
        <div className="text-xs text-muted mt-1">
            These filters remove individual events, not {units}. {capitalizeFirstLetter(units)} still count as long as
            one of their events of this type passes the filters.
            {!launched &&
                ` To keep ${units} out of the experiment, exclude them in the feature flag's release conditions.`}
        </div>
    )
}
