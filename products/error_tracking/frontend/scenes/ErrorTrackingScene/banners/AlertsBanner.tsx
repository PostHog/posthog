import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'
import { ReactNode } from 'react'

import { IconBell } from '@posthog/icons'

import { useOnMountEffect } from 'lib/hooks/useOnMountEffect'

import { AlertSetupModal } from './AlertSetupModal'
import { BannerCallout } from './BannerCallout'
import { errorTrackingConfigurationSettingUrl } from './configurationSettingUrl'
import { errorTrackingBannersLogic } from './errorTrackingBannersLogic'
import { TownCrierHog } from './townCrierHog'
import { ALERT_TRIGGER_ADJECTIVES, type AlertsRecommendation } from './types'

const ALERT_SETTINGS_URL = errorTrackingConfigurationSettingUrl('error-tracking-alerting')
const LIST_FORMAT = new Intl.ListFormat('en', { style: 'long', type: 'disjunction' })

// Mounts only while the banner is visible, so the "shown" event fires exactly when it was seen.
export function AlertsBanner({
    recommendation,
    navigation,
}: {
    recommendation: AlertsRecommendation
    navigation?: ReactNode
}): JSX.Element {
    const { isAlertSetupOpen, alertSetupTriggerKey } = useValues(errorTrackingBannersLogic)
    const { dismissBanner, openAlertSetup, closeAlertSetup } = useActions(errorTrackingBannersLogic)
    const missing = (recommendation.meta.alerts ?? []).filter((alert) => !alert.enabled)
    const missingAdjectives = missing.map((alert) => ALERT_TRIGGER_ADJECTIVES[alert.key] ?? alert.key)

    useOnMountEffect(() => {
        posthog.capture('error_tracking_alerts_banner_shown', { missing_alert_count: missing.length })
    })

    return (
        <>
            <BannerCallout
                illustration={TownCrierHog}
                title={`You don't get alerts for ${LIST_FORMAT.format(missingAdjectives)} issues`}
                description="Send them to Slack, Teams, PagerDuty, or another destination."
                primaryAction={{
                    label: missing.length === 1 ? 'Set up alert' : 'Set up alerts',
                    icon: <IconBell />,
                    // With one alert left, skip the trigger step and set up that one.
                    onClick: () => openAlertSetup(missing.length === 1 ? missing[0].key : null),
                    dataAttr: 'error-tracking-alerts-banner-set-up',
                }}
                secondaryAction={{
                    label: 'Alert settings',
                    to: ALERT_SETTINGS_URL,
                    onClick: () => posthog.capture('error_tracking_alerts_banner_settings_clicked'),
                    dataAttr: 'error-tracking-alerts-banner-settings',
                }}
                navigation={navigation}
                onDismiss={() => dismissBanner('alerts')}
            />
            {isAlertSetupOpen && <AlertSetupModal triggerKey={alertSetupTriggerKey} onClose={closeAlertSetup} />}
        </>
    )
}
