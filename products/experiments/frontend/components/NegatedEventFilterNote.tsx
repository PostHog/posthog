import { hasNegatedEventFilter } from 'scenes/experiments/exposureContract'

import type { ExperimentExposureConfig } from '~/queries/schema/schema-general'

export function NegatedEventFilterNote({
    config,
    launched,
}: {
    config: ExperimentExposureConfig | undefined
    launched: boolean
}): JSX.Element | null {
    if (!hasNegatedEventFilter(config)) {
        return null
    }
    return (
        <div className="text-xs text-muted mt-1">
            A filter on an event property applies to each event. A user with a left-out event still counts if another of
            their events passes the filter.
            {!launched &&
                " To keep users out of the experiment, leave them out in the feature flag's release conditions."}
        </div>
    )
}
