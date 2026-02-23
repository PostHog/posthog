import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LinkedHogFunctions } from 'scenes/hog-functions/list/LinkedHogFunctions'

export function ErrorTrackingAlerting(): JSX.Element {
    const hasSpikeAlertingFeatureFlag = useFeatureFlag('ERROR_TRACKING_SPIKE_ALERTING')

    return (
        <LinkedHogFunctions
            type="internal_destination"
            subTemplateIds={[
                'error-tracking-issue-created',
                'error-tracking-issue-reopened',
                ...(hasSpikeAlertingFeatureFlag ? (['error-tracking-issue-spiking'] as const) : []),
            ]}
        />
    )
}
