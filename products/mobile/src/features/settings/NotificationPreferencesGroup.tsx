import type { ReactElement } from 'react'
import { ActivityIndicator, Platform, Switch, Text, View } from 'react-native'

import type { NotificationPreferenceKey } from '@/api/notificationPreferences'
import { Pressable44 } from '@/ui/Pressable44'
import { createStyles, useColors } from '@/ui/theme'
import { type } from '@/ui/tokens'

import { SettingsGroup } from './SettingsGroup'
import { SettingsRow } from './SettingsRow'
import { useNotificationPreferences } from './useNotificationPreferences'

const CHAT: { key: NotificationPreferenceKey; label: string; description: string }[] = [
    {
        key: 'mobile_push_chat_attention_enabled',
        label: 'Questions and problems',
        description: 'An agent needs your help, or a task fails or is canceled.',
    },
    {
        key: 'mobile_push_chat_mentions_enabled',
        label: 'Mentions and assignments',
        description: 'Someone mentions you or assigns a task to you.',
    },
    {
        key: 'mobile_push_chat_replies_enabled',
        label: 'Team replies',
        description: 'A teammate replies without mentioning you.',
    },
    {
        key: 'mobile_push_chat_completions_enabled',
        label: 'Agent replies',
        description: 'An agent replies or finishes a task.',
    },
    {
        key: 'mobile_push_chat_pr_outcomes_enabled',
        label: 'Pull request updates',
        description: 'A pull request from a chat is merged or closed.',
    },
]
const REPORT_UPDATES: typeof CHAT = [
    {
        key: 'mobile_push_report_attention_enabled',
        label: 'Questions and problems',
        description: 'Work on a report needs your help, fails, or is canceled.',
    },
    {
        key: 'mobile_push_report_completions_enabled',
        label: 'Work finished',
        description: 'An agent finishes work on a report.',
    },
    {
        key: 'mobile_push_report_pr_ready_enabled',
        label: 'Code ready for review',
        description: "A report's pull request is ready to review.",
    },
    {
        key: 'mobile_push_report_pr_outcomes_enabled',
        label: 'Pull request updates',
        description: "A report's pull request is merged or closed.",
    },
]

export function NotificationPreferencesGroup(): ReactElement {
    const styles = useStyles()
    const colors = useColors()
    const state = useNotificationPreferences()
    const preferences = state.preferences

    const row = (
        key: NotificationPreferenceKey,
        label: string,
        description?: string,
        parent?: NotificationPreferenceKey
    ): ReactElement => (
        <SettingsRow
            key={key}
            label={label}
            description={description}
            accessory={
                <Switch
                    {...(Platform.OS === 'web' ? { activeThumbColor: colors.white } : {})}
                    accessibilityLabel={label}
                    accessibilityHint={description}
                    testID={`notification-preference-${key}`}
                    value={preferences?.[key] ?? false}
                    disabled={
                        state.saving ||
                        (key !== 'mobile_push_enabled' && !preferences?.mobile_push_enabled) ||
                        Boolean(parent && !preferences?.[parent])
                    }
                    onValueChange={(value) => void state.change(key, value)}
                    trackColor={{ true: colors.switchOn, false: colors.switchOff }}
                    thumbColor={colors.white}
                />
            }
        />
    )

    return (
        <View testID="settings-notification-preferences">
            <SettingsGroup
                title="All notifications"
                footer="Applies to all projects and mobile devices on this account."
            >
                {state.loading ? (
                    <SettingsRow label="Loading settings" accessory={<ActivityIndicator color={colors.tertiary} />} />
                ) : null}
                {state.loadError ? (
                    <View style={styles.notice}>
                        <Text style={styles.message}>Couldn't load your settings. Try again.</Text>
                        <Pressable44 onPress={state.retry} testID="notification-preferences-retry">
                            <Text style={styles.retry}>Try again</Text>
                        </Pressable44>
                    </View>
                ) : null}
                {preferences ? row('mobile_push_enabled', 'Allow notifications', 'Includes snooze reminders.') : null}
                {state.saving ? (
                    <SettingsRow label="Saving settings" accessory={<ActivityIndicator color={colors.tertiary} />} />
                ) : null}
                {state.saveError ? (
                    <Text accessibilityRole="alert" style={[styles.message, styles.notice]}>
                        {state.saveError}
                    </Text>
                ) : null}
            </SettingsGroup>
            {preferences ? (
                <>
                    <SettingsGroup
                        title="Reports"
                        footer="Turning off snooze reminders cancels them on this device. Open the app on other devices to cancel theirs. Turning reminders back on only applies to new snoozes."
                    >
                        {row('mobile_push_reports_enabled', 'New reports', 'A new report is ready for you to review.')}
                        {row(
                            'mobile_push_report_updates_enabled',
                            'Work updates',
                            'Questions, completed work, and pull requests from reports.'
                        )}
                        {REPORT_UPDATES.map(({ key, label, description }) =>
                            row(key, label, description, 'mobile_push_report_updates_enabled')
                        )}
                        {row(
                            'mobile_push_snooze_enabled',
                            'Snooze reminders',
                            'A snoozed report returns to your inbox.'
                        )}
                    </SettingsGroup>
                    <SettingsGroup title="Chat">
                        {row('mobile_push_chat_enabled', 'Chat notifications', 'Messages and updates from your chats.')}
                        {CHAT.map(({ key, label, description }) =>
                            row(key, label, description, 'mobile_push_chat_enabled')
                        )}
                    </SettingsGroup>
                </>
            ) : null}
        </View>
    )
}

const useStyles = createStyles(({ colors }) => ({
    notice: { paddingHorizontal: 16, paddingVertical: 12 },
    message: { ...type.metaSmall, color: colors.secondary },
    retry: { ...type.body, color: colors.ink, paddingVertical: 8 },
}))
