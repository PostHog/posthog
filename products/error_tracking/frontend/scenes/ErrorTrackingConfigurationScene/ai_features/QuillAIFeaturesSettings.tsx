import { Button, Item, ItemActions, ItemContent, ItemDescription, Skeleton } from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { QuillSettingSwitch } from 'scenes/settings/components/QuillSettingSwitch'
import { AIAccessRequest } from 'scenes/settings/organization/AIAccessRequest'
import { urls } from 'scenes/urls'

import { QuillConfigurationSubsection } from '../QuillConfigurationSubsection'

export function QuillAIFeaturesSettings({
    settingsLoaded,
    settingsLoading,
    settingsLoadFailed,
    issueSummariesEnabled,
    onIssueSummariesChange,
    disabledReason,
    aiNotApprovedMessage,
    canManageAI,
}: {
    settingsLoaded: boolean
    settingsLoading: boolean
    settingsLoadFailed: boolean
    issueSummariesEnabled: boolean
    onIssueSummariesChange: (enabled: boolean) => void
    disabledReason: string | null
    aiNotApprovedMessage: string | null
    canManageAI: boolean
}): JSX.Element {
    return (
        <QuillConfigurationSubsection
            title="Issue summaries"
            description="When this is on, PostHog uses AI to summarize issues created after you turn it on: what happened, the likely cause, who is affected, and a next step. Each summary uses your organization's AI credits. Summaries also need your organization to approve AI data processing."
        >
            {settingsLoaded ? (
                <QuillSettingSwitch
                    dataAttr="error-tracking-ai-issue-summaries-switch"
                    label="Summarize new issues"
                    checked={issueSummariesEnabled}
                    onCheckedChange={onIssueSummariesChange}
                    disabled={settingsLoading}
                    disabledReason={disabledReason}
                />
            ) : settingsLoadFailed ? (
                <Item tone="destructive" size="sm">
                    <ItemContent>
                        <ItemDescription>Couldn't load this setting. Refresh the page to try again.</ItemDescription>
                    </ItemContent>
                </Item>
            ) : (
                <Skeleton className="w-60 h-8" />
            )}
            {aiNotApprovedMessage && (
                <Item tone="info" size="sm">
                    <ItemContent>
                        <ItemDescription>{`${aiNotApprovedMessage}.`}</ItemDescription>
                    </ItemContent>
                    <ItemActions>
                        {canManageAI ? (
                            <Button
                                variant="outline"
                                nativeButton={false}
                                render={
                                    <LinkPrimitive
                                        to={urls.settings('organization-details', 'organization-ai-consent')}
                                    />
                                }
                                data-attr="error-tracking-ai-features-ai-settings"
                            >
                                Manage AI settings
                            </Button>
                        ) : (
                            <AIAccessRequest />
                        )}
                    </ItemActions>
                </Item>
            )}
        </QuillConfigurationSubsection>
    )
}
