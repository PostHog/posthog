import { type ReactElement, useEffect } from 'react'
import { ActivityIndicator, type StyleProp, Text, View, type ViewStyle } from 'react-native'

import { useAuthStore } from '@/auth/authStore'
import { signOutCopy } from '@/features/accounts/signOutCopy'
import { track } from '@/lib/analytics'
import { Pressable44 } from '@/ui/Pressable44'
import { createStyles, useColors } from '@/ui/theme'
import { radii, type } from '@/ui/tokens'

interface SignOutConfirmProps {
    from: 'settings' | 'nav_menu' | 'session_ended'
    /** An account key, or every account on this phone. */
    target: string | 'all'
    pending: boolean
    error?: string | null
    onCancel: () => void
    onConfirm: () => void
    /** A quieter action under the buttons, such as signing out of every account instead. */
    secondary?: { label: string; onPress: () => void; testID: string } | null
    style?: StyleProp<ViewStyle>
    /** `{testIDPrefix}-sign-out-confirm`, `-cancel` and `-confirm-button`. */
    testIDPrefix: string
}

// Sign out asks for confirmation in place, which works the same on iOS, Android and web.
export function SignOutConfirm({
    from,
    target,
    pending,
    error,
    onCancel,
    onConfirm,
    secondary,
    style,
    testIDPrefix,
}: SignOutConfirmProps): ReactElement {
    const styles = useStyles()
    const colors = useColors()
    const accounts = useAuthStore((state) => state.accounts)
    const activeKey = useAuthStore((state) => state.activeAccountKey)
    const copy = signOutCopy(target, accounts, activeKey)
    const scope = target === 'all' ? 'all' : 'one'

    // Callers mount this only while they ask, and key it by target, so a mount is one confirmation shown.
    // biome-ignore lint/correctness/useExhaustiveDependencies: one event per confirmation, not per prop change.
    useEffect(() => {
        track('mobile_sign_out_confirm_shown', { from, scope, account_count: accounts.length })
    }, [])

    const cancel = (): void => {
        track('mobile_sign_out_cancelled', { from, scope })
        onCancel()
    }
    const confirm = (): void => {
        track('mobile_sign_out_confirmed', {
            from,
            scope,
            account_count: accounts.length,
            active: target === activeKey,
        })
        onConfirm()
    }

    return (
        <View style={[styles.confirm, style]} testID={`${testIDPrefix}-sign-out-confirm`}>
            <Text style={styles.title}>{copy.title}</Text>
            <Text style={styles.body}>{copy.body}</Text>
            {error ? <Text style={styles.error}>{error}</Text> : null}
            <View style={styles.actions}>
                <Pressable44
                    onPress={cancel}
                    disabled={pending}
                    pressedBackground={colors.sunken}
                    style={[styles.button, styles.cancel]}
                    testID={`${testIDPrefix}-sign-out-cancel`}
                >
                    <Text style={styles.cancelText}>Cancel</Text>
                </Pressable44>
                <Pressable44
                    onPress={confirm}
                    disabled={pending}
                    accessibilityState={{ busy: pending, disabled: pending }}
                    pressedBackground={colors.pressOverlay}
                    style={[styles.button, styles.destructive]}
                    testID={`${testIDPrefix}-sign-out-confirm-button`}
                >
                    {pending ? (
                        <ActivityIndicator color={colors.onAccent} />
                    ) : (
                        <Text style={styles.destructiveText}>{error ? 'Try again' : 'Sign out'}</Text>
                    )}
                </Pressable44>
            </View>
            {secondary ? (
                <Pressable44
                    onPress={secondary.onPress}
                    disabled={pending}
                    pressedStyle={styles.secondaryPressed}
                    style={styles.secondary}
                    testID={secondary.testID}
                >
                    <Text style={styles.secondaryText}>{secondary.label}</Text>
                </Pressable44>
            ) : null}
        </View>
    )
}

const useStyles = createStyles(({ colors }) => ({
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
    error: {
        ...type.bodySmall,
        color: colors.orange,
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
        backgroundColor: colors.surface,
    },
    cancelText: {
        ...type.buttonSmall,
        color: colors.ink,
    },
    destructive: {
        backgroundColor: colors.orange,
    },
    secondary: {
        height: 44,
        marginTop: 4,
        alignSelf: 'center',
        alignItems: 'center',
        justifyContent: 'center',
    },
    secondaryPressed: {
        opacity: 0.6,
    },
    secondaryText: {
        ...type.buttonSmall,
        color: colors.secondary,
    },
    // Sign out stays orange because it is destructive; `onAccent` keeps its label legible on the brighter dark-mode orange.
    destructiveText: {
        ...type.buttonSmall,
        color: colors.onAccent,
    },
}))
