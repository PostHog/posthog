import { useActions, useValues } from 'kea'

import { LemonBanner, LemonSegmentedButton, LemonSelect, LemonSkeleton, LemonSwitch } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import type { SlackReplyDefaultEnumApi } from '../generated/api.schemas'
import { SlackAppSettingRow } from './SlackAppSettingRow'
import { SlackAppSettingsGroup } from './SlackAppSettingsGroup'
import { slackAppSettingsLogic } from './slackAppSettingsLogic'
import {
    POSTHOG_DEFAULT_THREAD_JOIN_MODE,
    POSTHOG_DEFAULT_UNTAGGED_MODE,
    THREAD_JOIN_OPTIONS,
    UNTAGGED_MODE_OPTIONS,
    replyModeLabel,
} from './slackReplyModeOptions'

const WORKSPACE_DEFAULT = 'workspace_default'

export function SlackAppPersonalSettings(): JSX.Element {
    const { settings, settingsLoading, personalSettingsDisabledReason } = useValues(slackAppSettingsLogic)
    const { updatePersonalSettings } = useActions(slackAppSettingsLogic)

    if (settingsLoading && !settings) {
        return <LemonSkeleton className="h-60" />
    }
    if (!settings) {
        return <LemonBanner type="error">Couldn't load your Slack settings. Refresh the page to try again.</LemonBanner>
    }

    const personal = settings.personal
    const workspaceName = settings.slack_workspace_name ?? 'this Slack workspace'

    if (!personal.slack_user_id) {
        return (
            <LemonBanner
                type="info"
                action={{
                    children: 'Link Slack account',
                    to: urls.settings('user-personal-integrations', 'personal-integrations-slack'),
                }}
            >
                Link your Slack account in {workspaceName} to change how PostHog works for you there.
            </LemonBanner>
        )
    }

    const inherits = (setting: SlackReplyDefaultEnumApi): boolean => personal.inherited_settings.includes(setting)
    const defaultUntaggedOption = (
        workspaceMode: (typeof UNTAGGED_MODE_OPTIONS)[number]['value'] | null
    ): { value: string; label: string; tooltip: string } => ({
        value: WORKSPACE_DEFAULT,
        label: 'Default',
        tooltip: `Workspace default: ${replyModeLabel(UNTAGGED_MODE_OPTIONS, workspaceMode ?? POSTHOG_DEFAULT_UNTAGGED_MODE)}`,
    })
    const workspaceThreadJoinMode = settings.workspace.thread_join_mode ?? POSTHOG_DEFAULT_THREAD_JOIN_MODE

    return (
        <div className="flex flex-col gap-4 max-w-200">
            <p className="text-secondary m-0">
                Linked to your Slack account in <strong className="text-primary">{workspaceName}</strong>.
            </p>

            <SlackAppSettingsGroup title="Defaults">
                <SlackAppSettingRow label="Default project" description="The project PostHog uses when you tag it.">
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
                </SlackAppSettingRow>
                <SlackAppSettingRow
                    label="Pick the model for me"
                    description="PostHog picks the model for each task you start from Slack."
                >
                    <LemonSwitch
                        checked={personal.auto_model_choice}
                        onChange={(checked) => updatePersonalSettings({ auto_model_choice: checked })}
                        disabledReason={personalSettingsDisabledReason}
                        data-attr="slack-app-settings-auto-model"
                    />
                </SlackAppSettingRow>
                {personal.chatgpt_apps_enabled !== null ? (
                    <SlackAppSettingRow
                        label="ChatGPT apps"
                        description="Your ChatGPT plan is connected. Let tasks you start from Slack use the apps on it. People who join your threads can use them too. Applies to new tasks."
                    >
                        <LemonSwitch
                            checked={personal.chatgpt_apps_enabled}
                            onChange={(checked) => updatePersonalSettings({ chatgpt_apps_enabled: checked })}
                            disabledReason={personalSettingsDisabledReason}
                            data-attr="slack-app-settings-chatgpt-apps"
                        />
                    </SlackAppSettingRow>
                ) : null}
            </SlackAppSettingsGroup>

            <SlackAppSettingsGroup
                title="Replies"
                description="What PostHog does with messages that don't tag it, and when others tag it in your threads."
            >
                <SlackAppSettingRow
                    label="Replies in your threads"
                    description="Anyone replies in a thread you started with PostHog, without tagging it."
                >
                    <LemonSegmentedButton
                        size="small"
                        value={inherits('untagged_followup_mode') ? WORKSPACE_DEFAULT : personal.untagged_followup_mode}
                        onChange={(value) =>
                            updatePersonalSettings({
                                untagged_followup_mode:
                                    value === WORKSPACE_DEFAULT
                                        ? null
                                        : (value as typeof personal.untagged_followup_mode),
                            })
                        }
                        options={[
                            defaultUntaggedOption(settings.workspace.untagged_followup_mode),
                            ...UNTAGGED_MODE_OPTIONS,
                        ]}
                        disabledReason={personalSettingsDisabledReason}
                        data-attr="slack-app-settings-untagged-replies"
                    />
                </SlackAppSettingRow>
                <SlackAppSettingRow label="Questions in channels" description="You ask a question in a channel.">
                    <LemonSegmentedButton
                        size="small"
                        value={inherits('untagged_question_mode') ? WORKSPACE_DEFAULT : personal.untagged_question_mode}
                        onChange={(value) =>
                            updatePersonalSettings({
                                untagged_question_mode:
                                    value === WORKSPACE_DEFAULT
                                        ? null
                                        : (value as typeof personal.untagged_question_mode),
                            })
                        }
                        options={[
                            defaultUntaggedOption(settings.workspace.untagged_question_mode),
                            ...UNTAGGED_MODE_OPTIONS,
                        ]}
                        disabledReason={personalSettingsDisabledReason}
                        data-attr="slack-app-settings-untagged-questions"
                    />
                </SlackAppSettingRow>
                <SlackAppSettingRow
                    label="Others in your threads"
                    description="Someone else tags PostHog in a thread you started."
                >
                    <LemonSelect
                        className="w-64"
                        value={inherits('thread_join_mode') ? WORKSPACE_DEFAULT : personal.thread_join_mode}
                        onChange={(value) =>
                            updatePersonalSettings({
                                thread_join_mode:
                                    value === WORKSPACE_DEFAULT ? null : (value as typeof personal.thread_join_mode),
                            })
                        }
                        options={[
                            {
                                value: WORKSPACE_DEFAULT,
                                label: `Default (${replyModeLabel(THREAD_JOIN_OPTIONS, workspaceThreadJoinMode)})`,
                            },
                            ...THREAD_JOIN_OPTIONS,
                        ]}
                        disabledReason={personalSettingsDisabledReason}
                        data-attr="slack-app-settings-thread-join"
                    />
                </SlackAppSettingRow>
            </SlackAppSettingsGroup>

            <SlackAppSettingsGroup title="Tips">
                <SlackAppSettingRow label="Feature tips" description="Short tips about things PostHog can do in Slack.">
                    <LemonSwitch
                        checked={personal.feature_tips_enabled}
                        onChange={(checked) => updatePersonalSettings({ feature_tips_enabled: checked })}
                        disabledReason={personalSettingsDisabledReason}
                        data-attr="slack-app-settings-feature-tips"
                    />
                </SlackAppSettingRow>
            </SlackAppSettingsGroup>
        </div>
    )
}
