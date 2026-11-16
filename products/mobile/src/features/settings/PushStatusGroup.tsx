import { type ReactElement, useEffect } from 'react'
import { ActivityIndicator, Linking, Text, View } from 'react-native'

import { refreshPushPermission, syncPushRegistration } from '@/features/notifications/pushRegistration'
import { type PushState, usePushStore } from '@/features/notifications/pushStore'
import type { PushUnavailableReason } from '@/features/notifications/pushSupport'
import { track } from '@/lib/analytics'
import { useAsyncAction } from '@/lib/useAsyncAction'
import { Pressable44 } from '@/ui/Pressable44'
import { createStyles, useColors } from '@/ui/theme'
import { radii, type } from '@/ui/tokens'

import { SettingsGroup } from './SettingsGroup'
import { SettingsRow } from './SettingsRow'

const UNAVAILABLE: Record<PushUnavailableReason, string> = {
    web: 'Not available on the web',
    simulator: 'Needs a physical device',
    expo_go: 'Needs a development build',
}

function statusLabel(push: PushState): string {
    switch (push.permission) {
        case 'unavailable':
            return push.unavailableReason ? UNAVAILABLE[push.unavailableReason] : 'Not available'
        case 'granted':
            if (push.error) {
                return "Couldn't turn on"
            }
            if (push.token) {
                return 'On'
            }
            return 'Turning on'
        case 'denied':
            return push.canAskAgain ? 'Off' : 'Blocked in system settings'
        default:
            return 'Off'
    }
}

function shortToken(token: string): string {
    const inner = /^ExponentPushToken\[(.+)\]$/.exec(token)?.[1]
    if (!inner || inner.length <= 12) {
        return token
    }
    return `ExponentPushToken[${inner.slice(0, 6)}…${inner.slice(-4)}]`
}

export function PushStatusGroup(): ReactElement {
    const styles = useStyles()
    const colors = useColors()
    const push = usePushStore()
    const openSystemSettings = push.permission === 'denied' && !push.canAskAgain
    const canEnable =
        push.permission === 'unknown' ||
        push.permission === 'undetermined' ||
        push.permission === 'denied' ||
        (push.permission === 'granted' && (!push.token || push.error !== null) && !push.registering)

    useEffect(() => {
        void refreshPushPermission()
    }, [])

    const enable = useAsyncAction(async () => {
        track('mobile_push_enable_pressed', { action: openSystemSettings ? 'open_system_settings' : 'request' })
        if (openSystemSettings) {
            await Linking.openSettings()
            return
        }
        await syncPushRegistration('always')
    })
    const busy = enable.pending || push.registering

    return (
        <SettingsGroup
            title="Notifications"
            footer={
                push.error && push.permission === 'granted' ? `Couldn't register this device. ${push.error}` : undefined
            }
            testID="settings-push"
        >
            <SettingsRow
                label="Push notifications"
                value={busy ? undefined : statusLabel(push)}
                accessory={busy ? <ActivityIndicator color={colors.ink} /> : undefined}
                testID="settings-push-status"
            />
            {push.token ? (
                <SettingsRow
                    label="This device"
                    value={shortToken(push.token)}
                    monoValue
                    testID="settings-push-token"
                />
            ) : null}
            {canEnable && push.permission !== 'unavailable' ? (
                <View style={styles.actionRow}>
                    <Pressable44
                        onPress={() => void enable.run()}
                        disabled={busy}
                        accessibilityState={{ busy, disabled: busy }}
                        pressedBackground={colors.inkHover}
                        style={[styles.action, busy && styles.actionBusy]}
                        testID="settings-push-enable"
                    >
                        <Text style={styles.actionText}>
                            {openSystemSettings
                                ? 'Open system settings'
                                : push.error
                                  ? 'Try again'
                                  : 'Enable notifications'}
                        </Text>
                    </Pressable44>
                </View>
            ) : null}
        </SettingsGroup>
    )
}

const useStyles = createStyles(({ colors }) => ({
    actionRow: {
        paddingHorizontal: 16,
        paddingVertical: 12,
        alignItems: 'flex-start',
    },
    action: {
        height: 40,
        paddingHorizontal: 16,
        borderRadius: radii.pill,
        backgroundColor: colors.ink,
        alignItems: 'center',
        justifyContent: 'center',
    },
    actionBusy: {
        opacity: 0.6,
    },
    actionText: {
        ...type.buttonSmall,
        color: colors.onInk,
    },
}))
