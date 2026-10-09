import type { ReactElement } from 'react'
import { ActivityIndicator, type StyleProp, StyleSheet, Text, View, type ViewStyle } from 'react-native'

import { useAuthStore } from '@/auth/authStore'
import { Pressable44 } from '@/ui/Pressable44'
import { colors, radii, type } from '@/ui/tokens'

interface SignOutConfirmProps {
    pending: boolean
    onCancel: () => void
    onConfirm: () => void
    style?: StyleProp<ViewStyle>
    /** `{testIDPrefix}-sign-out-confirm`, `-cancel` and `-confirm-button`. */
    testIDPrefix: string
}

// Sign out asks for confirmation in place, which works the same on iOS, Android and web.
export function SignOutConfirm({
    pending,
    onCancel,
    onConfirm,
    style,
    testIDPrefix,
}: SignOutConfirmProps): ReactElement {
    const host = useAuthStore((state) => state.host)
    return (
        <View style={[styles.confirm, style]} testID={`${testIDPrefix}-sign-out-confirm`}>
            <Text style={styles.title}>Sign out of {host ? host.replace(/^https?:\/\//, '') : 'PostHog'}?</Text>
            <Text style={styles.body}>This device stops getting push notifications until you sign in again.</Text>
            <View style={styles.actions}>
                <Pressable44
                    onPress={onCancel}
                    disabled={pending}
                    pressedBackground={colors.sunken}
                    style={[styles.button, styles.cancel]}
                    testID={`${testIDPrefix}-sign-out-cancel`}
                >
                    <Text style={styles.cancelText}>Cancel</Text>
                </Pressable44>
                <Pressable44
                    onPress={onConfirm}
                    disabled={pending}
                    accessibilityState={{ busy: pending, disabled: pending }}
                    pressedBackground={colors.pressOverlay}
                    style={[styles.button, styles.destructive]}
                    testID={`${testIDPrefix}-sign-out-confirm-button`}
                >
                    {pending ? (
                        <ActivityIndicator color={colors.white} />
                    ) : (
                        <Text style={styles.destructiveText}>Sign out</Text>
                    )}
                </Pressable44>
            </View>
        </View>
    )
}

const styles = StyleSheet.create({
    confirm: {
        gap: 6,
    },
    title: {
        ...type.bodyStrong,
        color: colors.ink,
    },
    body: {
        ...type.bodySmall,
        color: colors.muted,
    },
    actions: {
        flexDirection: 'row',
        gap: 10,
        marginTop: 10,
    },
    button: {
        flex: 1,
        height: 44,
        borderRadius: radii.pill,
        alignItems: 'center',
        justifyContent: 'center',
    },
    cancel: {
        borderWidth: 1,
        borderColor: colors.border,
        backgroundColor: colors.white,
    },
    cancelText: {
        ...type.buttonSmall,
        color: colors.ink,
    },
    destructive: {
        backgroundColor: colors.orange,
    },
    destructiveText: {
        ...type.buttonSmall,
        color: colors.white,
    },
})
