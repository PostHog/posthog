import type { ReactElement } from 'react'
import { ActivityIndicator, Platform, StyleSheet, Switch, Text, View } from 'react-native'

import type { NotificationPreferenceKey } from '@/api/notificationPreferences'
import { Pressable44 } from '@/ui/Pressable44'
import { colors, type } from '@/ui/tokens'

import { SettingsGroup } from './SettingsGroup'
import { SettingsRow } from './SettingsRow'
import { useNotificationPreferences } from './useNotificationPreferences'

const CATEGORIES: { key: NotificationPreferenceKey; label: string }[] = [
    { key: 'mobile_push_enabled', label: 'Allow mobile push' },
    { key: 'mobile_push_tasks_enabled', label: 'Chat and task updates' },
    { key: 'mobile_push_reports_enabled', label: 'New reports' },
    { key: 'mobile_push_report_updates_enabled', label: 'Report updates' },
]
const WEB_SWITCH_PROPS = Platform.OS === 'web' ? { activeThumbColor: colors.white } : {}

export function NotificationPreferencesGroup(): ReactElement {
    const state = useNotificationPreferences()
    return (
        <SettingsGroup
            title="Notification preferences"
            footer="Chat and task updates are for work you start or continue in this mobile app. Continuing a chat here enables mobile updates and stops direct Slack alerts for its agent updates. Opening a chat alone does not enable updates. Report updates include progress and PRs ready to review. Preferences apply to your account on all devices. Enable notifications on this device to receive them. Snooze reminders are separate."
            testID="settings-notification-preferences"
        >
            {state.loading ? <SettingsRow label="Loading preferences" accessory={<ActivityIndicator />} /> : null}
            {state.loadError && !state.preferences ? (
                <View style={styles.notice}>
                    <Text style={styles.message}>Couldn't load notification preferences.</Text>
                    <Pressable44 onPress={state.retry} testID="notification-preferences-retry">
                        <Text style={styles.retry}>Try again</Text>
                    </Pressable44>
                </View>
            ) : null}
            {state.preferences
                ? CATEGORIES.map(({ key, label }) => (
                      <SettingsRow
                          key={key}
                          label={label}
                          accessory={
                              <Switch
                                  {...WEB_SWITCH_PROPS}
                                  accessibilityLabel={label}
                                  testID={`notification-preference-${key}`}
                                  value={state.preferences?.[key]}
                                  disabled={
                                      state.saving ||
                                      (key !== 'mobile_push_enabled' && !state.preferences?.mobile_push_enabled)
                                  }
                                  onValueChange={(value) => void state.change(key, value)}
                                  trackColor={{ true: colors.ink, false: colors.border }}
                                  thumbColor={colors.white}
                              />
                          }
                      />
                  ))
                : null}
            {state.saving ? <SettingsRow label="Saving preferences" accessory={<ActivityIndicator />} /> : null}
            {state.saveError ? (
                <Text accessibilityRole="alert" style={[styles.message, styles.notice]}>
                    {state.saveError}
                </Text>
            ) : null}
        </SettingsGroup>
    )
}

const styles = StyleSheet.create({
    notice: { paddingHorizontal: 16, paddingVertical: 12 },
    message: { ...type.metaSmall, color: colors.secondary },
    retry: { ...type.body, color: colors.ink, paddingVertical: 8 },
})
