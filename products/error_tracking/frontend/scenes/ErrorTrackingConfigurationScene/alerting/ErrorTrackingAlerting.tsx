import { useActions, useValues } from 'kea'

import { LemonBanner } from '@posthog/lemon-ui'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LinkedHogFunctions } from 'scenes/hog-functions/list/LinkedHogFunctions'
import { settingsLogic } from 'scenes/settings/settingsLogic'

import { ERROR_TRACKING_LOGIC_KEY } from '../../../utils'
import { spikeDetectionConfigLogic } from '../spike_detection/spikeDetectionConfigLogic'

export function ErrorTrackingAlerting(): JSX.Element {
    const { config, configLoading } = useValues(spikeDetectionConfigLogic)
    const hasSpikeAlertingFeatureFlag = useFeatureFlag('ERROR_TRACKING_SPIKE_ALERTING')
    const { selectSetting } = useActions(
        settingsLogic({ logicKey: ERROR_TRACKING_LOGIC_KEY, sectionId: 'environment-error-tracking' })
    )

    return (
        <div className="space-y-4">
            {!configLoading && !config && hasSpikeAlertingFeatureFlag && (
                <LemonBanner
                    type="info"
                    action={{
                        children: 'Take me there',
                        onClick: () => selectSetting('error-tracking-spike-detection'),
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
