import { useActions, useValues } from 'kea'

import { LemonBanner, LemonSkeleton, LemonSwitch, LemonTag, Link } from '@posthog/lemon-ui'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { organizationLogic } from 'scenes/organizationLogic'
import { AIAccessRequest } from 'scenes/settings/organization/AIAccessRequest'
import { urls } from 'scenes/urls'

import { aiConsentLogic } from '~/layout/ai/aiConsentLogic'

import { errorTrackingEditAccessDisabledReason } from '../../../utils'
import { aiFeaturesSettingsLogic } from './aiFeaturesSettingsLogic'
import { QuillAIFeaturesSettings } from './QuillAIFeaturesSettings'

const AI_NOT_APPROVED = 'AI features are off for your organization'

export function AIFeaturesSettings(): JSX.Element {
    const { settings, settingsLoading, settingsLoadFailed } = useValues(aiFeaturesSettingsLogic)
    const { setIssueSummariesEnabled } = useActions(aiFeaturesSettingsLogic)
    const { dataProcessingAccepted } = useValues(aiConsentLogic)
    const { isAdminOrOwner } = useValues(organizationLogic)
    const issueSummariesEnabled = !!settings?.ai_issue_summaries_enabled
    // An organization can withdraw approval after a project turns summaries on, so turning them off stays possible.
    const aiNotApprovedReason = !dataProcessingAccepted && !issueSummariesEnabled ? AI_NOT_APPROVED : null
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')

    if (todayRailNav) {
        return (
            <QuillAIFeaturesSettings
                settingsLoaded={!!settings}
                settingsLoading={settingsLoading}
                settingsLoadFailed={settingsLoadFailed}
                issueSummariesEnabled={issueSummariesEnabled}
                onIssueSummariesChange={setIssueSummariesEnabled}
                disabledReason={errorTrackingEditAccessDisabledReason() ?? aiNotApprovedReason}
                aiNotApprovedMessage={dataProcessingAccepted ? null : AI_NOT_APPROVED}
                canManageAI={!!isAdminOrOwner}
            />
        )
    }

    return (
        <div className="space-y-4">
            <div>
                <h3 className="font-semibold text-base mb-1">
                    Issue summaries
                    <LemonTag type="highlight" size="small" className="ml-1">
                        Beta
                    </LemonTag>
                </h3>
                <p className="text-muted-foreground">
                    When this is on, PostHog uses AI to summarize each new issue: what happened, the likely cause, who
                    is affected, and a next step. Each summary uses your organization's AI credits. Summaries also need
                    your organization to approve AI data processing.
                </p>
            </div>
            {settings ? (
                <LemonSwitch
                    data-attr="error-tracking-ai-issue-summaries-switch"
                    label="Summarize new issues"
                    checked={issueSummariesEnabled}
                    onChange={setIssueSummariesEnabled}
                    loading={settingsLoading}
                    disabledReason={errorTrackingEditAccessDisabledReason() ?? aiNotApprovedReason}
                    bordered
                />
            ) : settingsLoadFailed ? (
                <LemonBanner type="error">Couldn't load this setting. Refresh the page to try again.</LemonBanner>
            ) : (
                <LemonSkeleton className="w-60 h-10" />
            )}
            {!dataProcessingAccepted ? (
                <LemonBanner type="info">
                    {AI_NOT_APPROVED}.{' '}
                    {isAdminOrOwner ? (
                        <Link
                            to={urls.settings('organization-details', 'organization-ai-consent')}
                            data-attr="error-tracking-ai-features-ai-settings"
                        >
                            Manage AI settings
                        </Link>
                    ) : (
                        <div className="mt-2">
                            <AIAccessRequest />
                        </div>
                    )}
                </LemonBanner>
            ) : null}
        </div>
    )
}
