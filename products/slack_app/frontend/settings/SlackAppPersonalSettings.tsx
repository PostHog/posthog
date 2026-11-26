import { useActions, useValues } from 'kea'

import {
    LemonBadge,
    LemonBanner,
    LemonCollapse,
    LemonSegmentedButton,
    LemonSelect,
    LemonSkeleton,
    LemonSwitch,
} from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import type { SlackThreadJoinModeEnumApi, SlackUntaggedModeEnumApi } from '../generated/api.schemas'
import { SlackAppInstallPicker } from './SlackAppInstallPicker'
import { slackAppSettingsLogic } from './slackAppSettingsLogic'

const UNTAGGED_MODE_OPTIONS: { value: SlackUntaggedModeEnumApi; label: string }[] = [
    { value: 'ask', label: 'Ask first' },
    { value: 'auto', label: 'Automatically' },
    { value: 'never', label: 'Never' },
]

const THREAD_JOIN_OPTIONS: { value: SlackThreadJoinModeEnumApi; label: string }[] = [
    { value: 'allow', label: 'Let anyone join' },
    { value: 'ask_per_person', label: 'Ask me for each person' },
    { value: 'ask_per_thread', label: 'Ask me once for each thread' },
    { value: 'never', label: 'Ignore them' },
]

const WORKSPACE_DEFAULT = 'workspace_default'

function SettingsGroup({
    title,
    description,
    children,
}: {
    title?: string
    description?: string
    children: React.ReactNode
}): JSX.Element {
    return (
        <section className="flex flex-col gap-2">
            {title ? (
                <div>
                    <h3 className="text-sm font-semibold m-0">{title}</h3>
                    {description ? <p className="text-secondary text-xs m-0">{description}</p> : null}
                </div>
            ) : null}
            <div className="rounded border bg-surface-primary divide-y">{children}</div>
        </section>
    )
}

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
        <div className="flex flex-wrap items-center justify-between gap-x-6 gap-y-2 px-4 py-3">
            <div className="flex-1 min-w-60">
                <div className="font-semibold">{label}</div>
                <div className="text-secondary text-sm">{description}</div>
            </div>
            <div className="flex justify-end">{children}</div>
        </div>
    )
}

export function SlackAppPersonalSettings(): JSX.Element {
    const { settings, settingsLoading, slackIntegrations, integrationsLoading, personalSettingsDisabledReason } =
        useValues(slackAppSettingsLogic)
    const { updatePersonalSettings } = useActions(slackAppSettingsLogic)

    if ((integrationsLoading || settingsLoading) && !settings) {
        return <LemonSkeleton className="h-60" />
    }
    if (!slackIntegrations?.length) {
        return (
            <LemonBanner
                type="info"
                action={{ children: 'Go to integrations', to: urls.settings('environment-integrations') }}
            >
                Connect Slack to this project to change how PostHog works for you in Slack.
            </LemonBanner>
        )
    }
    if (!settings) {
        return <LemonBanner type="error">Couldn't load your Slack settings. Refresh the page to try again.</LemonBanner>
    }

    const personal = settings.personal
    const workspaceName = settings.slack_workspace_name ?? 'this Slack workspace'

    if (!personal.slack_user_id) {
        return (
            <div className="flex flex-col gap-2">
                <SlackAppInstallPicker />
                <LemonBanner
                    type="info"
                    action={{
                        children: 'Link Slack account',
                        to: urls.settings('user-personal-integrations', 'personal-integrations-slack'),
                    }}
                >
                    Link your Slack account in {workspaceName} to change how PostHog works for you there.
                </LemonBanner>
            </div>
        )
    }

    const changedAdvancedCount =
        Number(personal.thread_join_mode !== 'allow') +
        Number(!personal.feature_tips_enabled) +
        Number(personal.chatgpt_apps_enabled === true)

    return (
        <div className="flex flex-col gap-4 max-w-200">
            <div className="flex flex-wrap items-center justify-between gap-2">
                <p className="text-secondary m-0">
                    Linked to your Slack account in <strong className="text-primary">{workspaceName}</strong>.
                </p>
                <SlackAppInstallPicker />
            </div>

            <SettingsGroup title="Defaults">
                <SettingRow label="Default project" description="The project PostHog uses when you tag it.">
                    <LemonSelect
                        className="w-64"
                        value={personal.default_integration_id ?? WORKSPACE_DEFAULT}
                        onChange={(value) =>
                            updatePersonalSettings({
                                default_integration_id: value === WORKSPACE_DEFAULT ? null : Number(value),
                            })
                        }
                        options={[
                            { value: WORKSPACE_DEFAULT, label: 'Workspace default' },
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
                        disabledReason={personalSettingsDisabledReason}
                        data-attr="slack-app-settings-default-project"
                    />
                </SettingRow>
                <SettingRow
                    label="Pick the model for me"
                    description="PostHog picks the model for each task you start from Slack."
                >
                    <LemonSwitch
                        checked={personal.auto_model_choice}
                        onChange={(checked) => updatePersonalSettings({ auto_model_choice: checked })}
                        disabledReason={personalSettingsDisabledReason}
                        data-attr="slack-app-settings-auto-model"
                    />
                </SettingRow>
            </SettingsGroup>

            <SettingsGroup
                title="Messages that don't tag PostHog"
                description="PostHog can still pick up a message that doesn't tag it."
            >
                <SettingRow
                    label="Replies in your threads"
                    description="Anyone replies in a thread you started with PostHog, without tagging it."
                >
                    <LemonSegmentedButton
                        size="small"
                        value={personal.untagged_followup_mode}
                        onChange={(value) => updatePersonalSettings({ untagged_followup_mode: value })}
                        options={UNTAGGED_MODE_OPTIONS}
                        disabledReason={personalSettingsDisabledReason}
                        data-attr="slack-app-settings-untagged-replies"
                    />
                </SettingRow>
                <SettingRow label="Questions in channels" description="You ask a question in a channel.">
                    <LemonSegmentedButton
                        size="small"
                        value={personal.untagged_question_mode}
                        onChange={(value) => updatePersonalSettings({ untagged_question_mode: value })}
                        options={UNTAGGED_MODE_OPTIONS}
                        disabledReason={personalSettingsDisabledReason}
                        data-attr="slack-app-settings-untagged-questions"
                    />
                </SettingRow>
            </SettingsGroup>

            <LemonCollapse
                panels={[
                    {
                        key: 'advanced',
                        header: (
                            <span className="flex items-center gap-2">
                                Advanced options
                                {changedAdvancedCount > 0 ? <LemonBadge.Number count={changedAdvancedCount} /> : null}
                            </span>
                        ),
                        bodyClassName: 'p-0',
                        dataAttr: 'slack-app-settings-advanced',
                        content: (
                            <div className="divide-y">
                                <SettingRow
                                    label="Others in your threads"
                                    description="Someone else tags PostHog in a thread you started."
                                >
                                    <LemonSelect
                                        className="w-64"
                                        value={personal.thread_join_mode}
                                        onChange={(value) => updatePersonalSettings({ thread_join_mode: value })}
                                        options={THREAD_JOIN_OPTIONS}
                                        disabledReason={personalSettingsDisabledReason}
                                        data-attr="slack-app-settings-thread-join"
                                    />
                                </SettingRow>
                                {personal.chatgpt_apps_enabled !== null ? (
                                    <SettingRow
                                        label="ChatGPT apps"
                                        description="Your ChatGPT plan is connected. Let tasks you start from Slack use the apps on it. People who join your threads can use them too. Applies to new tasks."
                                    >
                                        <LemonSwitch
                                            checked={personal.chatgpt_apps_enabled}
                                            onChange={(checked) =>
                                                updatePersonalSettings({ chatgpt_apps_enabled: checked })
                                            }
                                            disabledReason={personalSettingsDisabledReason}
                                            data-attr="slack-app-settings-chatgpt-apps"
                                        />
                                    </SettingRow>
                                ) : null}
                                <SettingRow
                                    label="Feature tips"
                                    description="Short tips about things PostHog can do in Slack."
                                >
                                    <LemonSwitch
                                        checked={personal.feature_tips_enabled}
                                        onChange={(checked) =>
                                            updatePersonalSettings({ feature_tips_enabled: checked })
                                        }
                                        disabledReason={personalSettingsDisabledReason}
                                        data-attr="slack-app-settings-feature-tips"
                                    />
                                </SettingRow>
                            </div>
                        ),
                    },
                ]}
            />
        </div>
    )
}
