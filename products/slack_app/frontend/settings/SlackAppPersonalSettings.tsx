import { useActions, useValues } from 'kea'

import { LemonSelect, LemonSkeleton, LemonSwitch, Link } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import type { SlackThreadJoinModeEnumApi, SlackUntaggedModeEnumApi } from '../generated/api.schemas'
import { SlackAppInstallPicker } from './SlackAppInstallPicker'
import { slackAppSettingsLogic } from './slackAppSettingsLogic'

const UNTAGGED_MODE_OPTIONS: { value: SlackUntaggedModeEnumApi; label: string }[] = [
    { value: 'ask', label: 'Ask first' },
    { value: 'auto', label: 'Reply automatically' },
    { value: 'never', label: 'Never' },
]

const THREAD_JOIN_OPTIONS: { value: SlackThreadJoinModeEnumApi; label: string }[] = [
    { value: 'allow', label: 'Let anyone join' },
    { value: 'ask_per_person', label: 'Ask me for each person' },
    { value: 'ask_per_thread', label: 'Ask me once for each thread' },
    { value: 'never', label: 'Ignore them' },
]

const WORKSPACE_DEFAULT = 'workspace_default'

function SettingRow({
    label,
    description,
    children,
}: {
    label: string
    description: string
    children: JSX.Element
}): JSX.Element {
    return (
        <div className="flex flex-wrap items-center justify-between gap-4 py-3 border-t first:border-t-0">
            <div className="max-w-xl">
                <div className="font-semibold">{label}</div>
                <div className="text-secondary text-sm">{description}</div>
            </div>
            {children}
        </div>
    )
}

export function SlackAppPersonalSettings(): JSX.Element {
    const { settings, settingsLoading, slackIntegrations, integrationsLoading } = useValues(slackAppSettingsLogic)
    const { updatePersonalSettings } = useActions(slackAppSettingsLogic)

    if ((integrationsLoading || settingsLoading) && !settings) {
        return <LemonSkeleton className="h-40" />
    }
    if (!slackIntegrations?.length) {
        return (
            <p className="text-secondary m-0">
                Connect Slack to this project first.{' '}
                <Link to={urls.settings('environment-integrations')}>Go to integrations</Link>
            </p>
        )
    }
    if (!settings) {
        return <p className="text-secondary m-0">Couldn't load your Slack settings. Refresh the page to try again.</p>
    }

    const personal = settings.personal
    if (!personal.slack_user_id) {
        return (
            <div className="flex flex-col gap-2">
                <SlackAppInstallPicker />
                <p className="text-secondary m-0">
                    To change these settings,{' '}
                    <Link to={urls.settings('user-personal-integrations', 'personal-integrations-slack')}>
                        link your Slack account
                    </Link>{' '}
                    in {settings.slack_workspace_name ?? 'this Slack workspace'}.
                </p>
            </div>
        )
    }

    return (
        <div className="flex flex-col gap-2">
            <SlackAppInstallPicker />
            <div className="flex flex-col">
                <SettingRow label="Default project" description="The project PostHog uses when you tag it.">
                    <LemonSelect
                        value={personal.default_integration_id ?? WORKSPACE_DEFAULT}
                        onChange={(value) =>
                            updatePersonalSettings({
                                default_integration_id: value === WORKSPACE_DEFAULT ? null : Number(value),
                            })
                        }
                        options={[
                            { value: WORKSPACE_DEFAULT, label: 'Use the workspace default' },
                            ...personal.project_options.map((option) => ({
                                value: option.integration_id,
                                label: option.project_name,
                                labelInMenu: (
                                    <div>
                                        <div>{option.project_name}</div>
                                        <div className="text-secondary text-xs">{option.organization_name}</div>
                                    </div>
                                ),
                            })),
                        ]}
                        data-attr="slack-app-settings-default-project"
                    />
                </SettingRow>
                <SettingRow
                    label="Replies without a tag"
                    description="What PostHog does when you reply in its thread and don't tag it."
                >
                    <LemonSelect
                        value={personal.untagged_followup_mode}
                        onChange={(value) => updatePersonalSettings({ untagged_followup_mode: value })}
                        options={UNTAGGED_MODE_OPTIONS}
                        data-attr="slack-app-settings-untagged-replies"
                    />
                </SettingRow>
                <SettingRow
                    label="Questions without a tag"
                    description="What PostHog does when you ask a question in a channel and don't tag it."
                >
                    <LemonSelect
                        value={personal.untagged_question_mode}
                        onChange={(value) => updatePersonalSettings({ untagged_question_mode: value })}
                        options={UNTAGGED_MODE_OPTIONS}
                        data-attr="slack-app-settings-untagged-questions"
                    />
                </SettingRow>
                <SettingRow
                    label="Others join your thread"
                    description="What happens when someone else tags PostHog in a thread you started."
                >
                    <LemonSelect
                        value={personal.thread_join_mode}
                        onChange={(value) => updatePersonalSettings({ thread_join_mode: value })}
                        options={THREAD_JOIN_OPTIONS}
                        data-attr="slack-app-settings-thread-join"
                    />
                </SettingRow>
                <SettingRow
                    label="Pick the model for me"
                    description="PostHog picks the model for each task you start from Slack."
                >
                    <LemonSwitch
                        checked={personal.auto_model_choice}
                        onChange={(checked) => updatePersonalSettings({ auto_model_choice: checked })}
                        data-attr="slack-app-settings-auto-model"
                    />
                </SettingRow>
                <SettingRow label="Feature tips" description="Short tips about things PostHog can do in Slack.">
                    <LemonSwitch
                        checked={personal.feature_tips_enabled}
                        onChange={(checked) => updatePersonalSettings({ feature_tips_enabled: checked })}
                        data-attr="slack-app-settings-feature-tips"
                    />
                </SettingRow>
            </div>
        </div>
    )
}
