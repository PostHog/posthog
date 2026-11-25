import { useActions } from 'kea'
import posthog from 'posthog-js'
import { ReactNode } from 'react'

import { useOnMountEffect } from 'lib/hooks/useOnMountEffect'

import { BannerCallout } from './BannerCallout'
import { errorTrackingConfigurationSettingUrl } from './configurationSettingUrl'
import { errorTrackingBannersLogic } from './errorTrackingBannersLogic'
import { ReporterHog } from './reporterHog'

const AI_FEATURES_SETTINGS_URL = errorTrackingConfigurationSettingUrl('error-tracking-ai-features')

export function IssueSummariesBanner({ navigation }: { navigation?: ReactNode }): JSX.Element {
    const { dismissBanner } = useActions(errorTrackingBannersLogic)

    useOnMountEffect(() => {
        posthog.capture('error_tracking_issue_summaries_banner_shown')
    })

    return (
        <BannerCallout
            illustration={ReporterHog}
            title="Issue summaries are off for this project"
            description="Turn them on to get an AI summary of each new issue: what happened, the likely cause, who is affected, and a next step. Each summary uses your organization's AI credits."
            primaryAction={{
                // Opens the setting rather than turning it on, so the person reads the cost wording there first.
                label: 'Set up summaries',
                to: AI_FEATURES_SETTINGS_URL,
                onClick: () => posthog.capture('error_tracking_issue_summaries_banner_settings_clicked'),
                dataAttr: 'error-tracking-issue-summaries-banner-set-up',
            }}
            navigation={navigation}
            onDismiss={() => dismissBanner('issue_summaries')}
        />
    )
}
