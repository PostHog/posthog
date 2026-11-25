import { LemonTag } from '@posthog/lemon-ui'

import { EXPOSURE_DEFAULT_EVENT, isDefaultExposureConfig } from 'scenes/experiments/exposureContract'

import type { ExperimentExposureConfig } from '~/queries/schema/schema-general'

export function DefaultExposureEventNote({
    config,
    defaultExposureEvent,
}: {
    config: ExperimentExposureConfig | undefined
    /** The event the experiment's default exposure is counted on, as the backend resolves it. */
    defaultExposureEvent: string
}): JSX.Element | null {
    if (!config || !isDefaultExposureConfig(config)) {
        return null
    }
    return (
        <div className="text-xs text-muted mt-1" data-attr="experiment-exposure-default-event-note">
            <LemonTag size="small">{EXPOSURE_DEFAULT_EVENT}</LemonTag> is the default exposure event, so this counts the
            same exposures as the default
            {defaultExposureEvent !== EXPOSURE_DEFAULT_EVENT && (
                <>
                    {' '}
                    (<LemonTag size="small">{defaultExposureEvent}</LemonTag>)
                </>
            )}
            , narrowed by any filters you add. The experiment shows it as the default exposure. To use a custom
            exposure, pick a different event.
        </div>
    )
}
