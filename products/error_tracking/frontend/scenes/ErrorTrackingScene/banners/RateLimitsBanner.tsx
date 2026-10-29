import { useActions } from 'kea'
import posthog from 'posthog-js'
import { ReactNode } from 'react'

import { useOnMountEffect } from 'lib/hooks/useOnMountEffect'

import { BannerCallout } from './BannerCallout'
import { errorTrackingConfigurationSettingUrl } from './configurationSettingUrl'
import { errorTrackingBannersLogic } from './errorTrackingBannersLogic'
import { TrafficControllerHog } from './trafficControllerHog'

const RATE_LIMIT_SETTINGS_URL = errorTrackingConfigurationSettingUrl('error-tracking-rate-limits')

// Mounts only while the banner is visible, so the "shown" event fires exactly when it was seen.
export function RateLimitsBanner({ navigation }: { navigation?: ReactNode }): JSX.Element {
    const { dismissBanner } = useActions(errorTrackingBannersLogic)

    useOnMountEffect(() => {
        posthog.capture('error_tracking_rate_limits_banner_shown')
    })

    return (
        <BannerCallout
            illustration={TrafficControllerHog}
            title="Your project has no rate limit"
            description="Set one to drop exceptions above a rate you choose, so a runaway error loop can't flood the project."
            primaryAction={{
                label: 'Set rate limit',
                to: RATE_LIMIT_SETTINGS_URL,
                onClick: () =>
                    posthog.capture('error_tracking_rate_limit_setup_started', {
                        ui_source: 'rate_limits_banner',
                        rate_limit_key: 'project',
                    }),
                dataAttr: 'error-tracking-rate-limits-banner-set-up',
            }}
            navigation={navigation}
            onDismiss={() => dismissBanner('rate_limits')}
        />
    )
}
