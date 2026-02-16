import { useValues } from 'kea'

import { LemonBanner } from '@posthog/lemon-ui'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LinkedHogFunctions } from 'scenes/hog-functions/list/LinkedHogFunctions'
import { urls } from 'scenes/urls'

import { spikeDetectionConfigLogic } from '../spike_detection/spikeDetectionConfigLogic'

export function ErrorTrackingAlerting(): JSX.Element {
    const { config, configLoading } = useValues(spikeDetectionConfigLogic)
    const hasSpikeAlertingFeatureFlag = useFeatureFlag('ERROR_TRACKING_SPIKE_ALERTING')

    return (
        <div className="space-y-4">
            {!configLoading && !config && hasSpikeAlertingFeatureFlag && (
                <LemonBanner
                    type="info"
                    action={{
                        children: 'Take me there',
                        to:
                            urls.errorTrackingConfiguration() +
                            '?tab=error-tracking-spike-detection#selectedSetting=error-tracking-spike-detection',
                    }}
                >
                    Spike detection is not enabled. You will not be able to create spike alerts until you enable it in
                    the <strong>Spike detection</strong> tab.
                </LemonBanner>
            )}
            <LinkedHogFunctions
                type="internal_destination"
                subTemplateIds={[
                    'error-tracking-issue-created',
                    'error-tracking-issue-reopened',
                    ...(config && hasSpikeAlertingFeatureFlag ? (['error-tracking-issue-spiking'] as const) : []),
                ]}
            />
        </div>
    )
}
