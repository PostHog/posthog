import type { ReactElement } from 'react'
import { ActivityIndicator, Platform, Switch, Text, View } from 'react-native'

import type { NotificationPreferenceKey } from '@/api/notificationPreferences'
import { Pressable44 } from '@/ui/Pressable44'
import { createStyles, useColors } from '@/ui/theme'
import { type } from '@/ui/tokens'

import { SettingsGroup } from './SettingsGroup'
import { SettingsRow } from './SettingsRow'
import { useNotificationPreferences } from './useNotificationPreferences'

const CATEGORIES: { key: NotificationPreferenceKey; label: string }[] = [
    { key: 'mobile_push_enabled', label: 'Allow mobile push' },
    { key: 'mobile_push_tasks_enabled', label: 'Chat and task updates' },
    { key: 'mobile_push_reports_enabled', label: 'New reports' },
    { key: 'mobile_push_report_updates_enabled', label: 'Report updates' },
]
export function NotificationPreferencesGroup(): ReactElement {
    const styles = useStyles()
    const colors = useColors()
    const webSwitchProps = Platform.OS === 'web' ? { activeThumbColor: colors.white } : {}
    const state = useNotificationPreferences()
    return (
        <SettingsGroup title="Notification preferences" testID="settings-notification-preferences">
            {state.loading ? (
                <SettingsRow label="Loading preferences" accessory={<ActivityIndicator color={colors.tertiary} />} />
            ) : null}
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
                                  {...webSwitchProps}
                                  accessibilityLabel={label}
                                  testID={`notification-preference-${key}`}
                                  value={state.preferences?.[key]}
                                  disabled={
                                      state.saving ||
                                      (key !== 'mobile_push_enabled' && !state.preferences?.mobile_push_enabled)
                                  }
                                  onValueChange={(value) => void state.change(key, value)}
                                  trackColor={{ true: colors.switchOn, false: colors.switchOff }}
                                  thumbColor={colors.white}
                              />
                          }
                      />
                  ))
                : null}
            {state.saving ? (
                <SettingsRow label="Saving preferences" accessory={<ActivityIndicator color={colors.tertiary} />} />
            ) : null}
            {state.saveError ? (
                <Text accessibilityRole="alert" style={[styles.message, styles.notice]}>
                    {state.saveError}
                </Text>
            ) : null}
        </SettingsGroup>
    )
}

const useStyles = createStyles(({ colors }) => ({
    notice: { paddingHorizontal: 16, paddingVertical: 12 },
    message: { ...type.metaSmall, color: colors.secondary },
    retry: { ...type.body, color: colors.ink, paddingVertical: 8 },
}))
