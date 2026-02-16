import { useValues } from 'kea'

import { LemonBanner } from '@posthog/lemon-ui'

import { LinkedHogFunctions } from 'scenes/hog-functions/list/LinkedHogFunctions'

import { spikeDetectionConfigLogic } from '../spike_detection/spikeDetectionConfigLogic'

export function ErrorTrackingAlerting(): JSX.Element {
    const { config, configLoading } = useValues(spikeDetectionConfigLogic)

    return (
        <div className="space-y-4">
            {!configLoading && !config && (
                <LemonBanner type="warning">
                    Spike detection is not enabled. Spike alerts will not fire until you enable it in the{' '}
                    <strong>Spike detection</strong> tab.
                </LemonBanner>
            )}
            <LinkedHogFunctions
                type="internal_destination"
                subTemplateIds={[
                    'error-tracking-issue-created',
                    'error-tracking-issue-reopened',
                    'error-tracking-issue-spiking',
                ]}
            />
        </div>
    )
}
