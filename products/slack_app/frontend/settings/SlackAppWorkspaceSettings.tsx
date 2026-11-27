import { useActions, useValues } from 'kea'

import { LemonBanner, LemonSegmentedButton, LemonSelect, LemonSkeleton, LemonSwitch } from '@posthog/lemon-ui'

import type { SlackUntaggedModeEnumApi } from '../generated/api.schemas'
import { SlackAppSettingRow } from './SlackAppSettingRow'
import { SlackAppSettingsGroup } from './SlackAppSettingsGroup'
import { slackAppSettingsLogic } from './slackAppSettingsLogic'
import {
    CHANNEL_WELCOME_OPTIONS,
    POSTHOG_DEFAULT_THREAD_JOIN_MODE,
    POSTHOG_DEFAULT_UNTAGGED_MODE,
    THREAD_JOIN_OPTIONS,
    UNTAGGED_MODE_OPTIONS,
    replyModeLabel,
} from './slackReplyModeOptions'

const NO_DEFAULT = 'no_default'

export function SlackAppWorkspaceSettings(): JSX.Element {
    const { settings, settingsLoading, workspaceSettingsDisabledReason } = useValues(slackAppSettingsLogic)
    const { updateWorkspaceSettings } = useActions(slackAppSettingsLogic)

    if (settingsLoading && !settings) {
        return <LemonSkeleton className="h-60" />
    }
    if (!settings) {
        return (
            <LemonBanner type="error">Couldn't load the workspace settings. Refresh the page to try again.</LemonBanner>
        )
    }

    const workspace = settings.workspace
    const defaultUntaggedOption = {
        value: NO_DEFAULT,
        label: 'Default',
        tooltip: `PostHog default: ${replyModeLabel(UNTAGGED_MODE_OPTIONS, POSTHOG_DEFAULT_UNTAGGED_MODE)}`,
    }

    return (
        <div className="flex flex-col gap-4 max-w-200">
            <SlackAppSettingsGroup title="Defaults">
                <SlackAppSettingRow
                    label="Default project"
                    description="The project PostHog uses when someone tags it and hasn't picked their own."
                >
                    <LemonSelect
                        className="w-64"
                        value={workspace.default_integration_id ?? NO_DEFAULT}
                        onChange={(value) =>
                            updateWorkspaceSettings({
                                default_integration_id: value === NO_DEFAULT ? null : Number(value),
                            })
                        }
                        options={[
                            { value: NO_DEFAULT, label: 'No default' },
                            ...settings.personal.project_options.map((option) => ({
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
                        disabledReason={workspaceSettingsDisabledReason}
                        data-attr="slack-app-settings-workspace-default-project"
                    />
                </SlackAppSettingRow>
                <SlackAppSettingRow
                    label="Greeting in new channels"
                    description="Where PostHog says hello when someone adds it to a channel."
                >
                    <LemonSelect
                        className="w-64"
                        value={workspace.channel_welcome_mode}
                        onChange={(value) => updateWorkspaceSettings({ channel_welcome_mode: value })}
                        options={CHANNEL_WELCOME_OPTIONS}
                        disabledReason={workspaceSettingsDisabledReason}
                        data-attr="slack-app-settings-channel-welcome"
                    />
                </SlackAppSettingRow>
            </SlackAppSettingsGroup>

            <SlackAppSettingsGroup
                title="Reply defaults"
                description="For people who haven't picked their own. Each person can still change theirs."
            >
                <SlackAppSettingRow
                    label="Replies in threads"
                    description="Someone replies in a thread started with PostHog, without tagging it."
                >
                    <LemonSegmentedButton
                        size="small"
                        value={workspace.untagged_followup_mode ?? NO_DEFAULT}
                        onChange={(value) =>
                            updateWorkspaceSettings({
                                untagged_followup_mode:
                                    value === NO_DEFAULT ? null : (value as SlackUntaggedModeEnumApi),
                            })
                        }
                        options={[defaultUntaggedOption, ...UNTAGGED_MODE_OPTIONS]}
                        disabledReason={workspaceSettingsDisabledReason}
                        data-attr="slack-app-settings-workspace-untagged-replies"
                    />
                </SlackAppSettingRow>
                <SlackAppSettingRow
                    label="Questions in channels"
                    description="Someone asks a question in a channel without tagging PostHog."
                >
                    <LemonSegmentedButton
                        size="small"
                        value={workspace.untagged_question_mode ?? NO_DEFAULT}
                        onChange={(value) =>
                            updateWorkspaceSettings({
                                untagged_question_mode:
                                    value === NO_DEFAULT ? null : (value as SlackUntaggedModeEnumApi),
                            })
                        }
                        options={[defaultUntaggedOption, ...UNTAGGED_MODE_OPTIONS]}
                        disabledReason={workspaceSettingsDisabledReason}
                        data-attr="slack-app-settings-workspace-untagged-questions"
                    />
                </SlackAppSettingRow>
                <SlackAppSettingRow
                    label="Others in threads"
                    description="Someone else tags PostHog in a thread another person started."
                >
                    <LemonSelect
                        className="w-64"
                        value={workspace.thread_join_mode ?? NO_DEFAULT}
                        onChange={(value) =>
                            updateWorkspaceSettings({ thread_join_mode: value === NO_DEFAULT ? null : value })
                        }
                        options={[
                            {
                                value: NO_DEFAULT,
                                label: `Default (${replyModeLabel(THREAD_JOIN_OPTIONS, POSTHOG_DEFAULT_THREAD_JOIN_MODE)})`,
                            },
                            ...THREAD_JOIN_OPTIONS,
                        ]}
                        disabledReason={workspaceSettingsDisabledReason}
                        data-attr="slack-app-settings-workspace-thread-join"
                    />
                </SlackAppSettingRow>
            </SlackAppSettingsGroup>

            <SlackAppSettingsGroup title="Shared channels">
                <SlackAppSettingRow
                    label="Reply in channels shared with other organizations"
                    description="When this is off, PostHog stays quiet in Slack Connect channels. When it is on, someone in each shared channel still approves PostHog the first time."
                >
                    <LemonSwitch
                        checked={workspace.external_channels_enabled}
                        onChange={(checked) => updateWorkspaceSettings({ external_channels_enabled: checked })}
                        disabledReason={workspaceSettingsDisabledReason}
                        data-attr="slack-app-settings-external-channels"
                    />
                </SlackAppSettingRow>
            </SlackAppSettingsGroup>
        </div>
    )
}
