import type { ReactElement } from 'react'
import { ActivityIndicator, Text, View } from 'react-native'

import type { StoredAccount } from '@/auth/authStore'
import { AccountActionButton } from '@/features/accounts/AccountActionButton'
import { AccountIdentity } from '@/features/accounts/AccountIdentity'
import { CheckIcon } from '@/ui/icons/CheckIcon'
import { Pressable44 } from '@/ui/Pressable44'
import { createStyles, useColors } from '@/ui/theme'
import { iconSizes, type } from '@/ui/tokens'

import { SignOutConfirm } from './SignOutConfirm'

interface AccountSettingsRowProps {
    account: StoredAccount
    active: boolean
    /** How copy names this account, from `accountLabel`. */
    label: string
    /** A switch to this account is in flight. */
    switching: boolean
    /** Another switch or a sign out is in flight. */
    disabled: boolean
    switchFailed: boolean
    /** Switches to the account, or opens sign-in for one that needs it. */
    onPress: () => void
    onRetrySwitch: () => void
    confirmingSignOut: boolean
    signOutPending: boolean
    signOutError: string | null
    onStartSignOut: () => void
    onCancelSignOut: () => void
    onConfirmSignOut: () => void
}

/** One account in the Settings Accounts group, with its own Sign out that confirms inside the row. */
export function AccountSettingsRow({
    account,
    active,
    label,
    switching,
    disabled,
    switchFailed,
    onPress,
    onRetrySwitch,
    confirmingSignOut,
    signOutPending,
    signOutError,
    onStartSignOut,
    onCancelSignOut,
    onConfirmSignOut,
}: AccountSettingsRowProps): ReactElement {
    const styles = useStyles()
    const colors = useColors()
    const testKey = active ? 'active' : account.key
    const status = account.needsSignIn ? (
        <Text style={styles.warn}>Sign in again</Text>
    ) : active ? (
        <View style={styles.activeStatus}>
            <CheckIcon size={iconSizes.small} />
            <Text style={styles.activeText}>Active</Text>
        </View>
    ) : null
    return (
        <View testID={`settings-account-${testKey}`}>
            <View style={styles.row}>
                <Pressable44
                    onPress={onPress}
                    disabled={active || disabled || switching}
                    accessibilityRole="radio"
                    accessibilityLabel={account.needsSignIn ? `${label}, sign in again` : label}
                    accessibilityState={{ checked: active, busy: switching, disabled: disabled || switching }}
                    pressedBackground={colors.background}
                    style={styles.main}
                    testID={`settings-account-${testKey}-open`}
                >
                    <AccountIdentity account={account} size="regular" status={status} />
                    {switching ? <ActivityIndicator color={colors.ink} accessibilityLabel="Switching" /> : null}
                </Pressable44>
                <AccountActionButton
                    label="Sign out"
                    onPress={onStartSignOut}
                    disabled={disabled || switching || confirmingSignOut}
                    accessibilityLabel={`Sign out of ${label}`}
                    testID={`settings-account-${testKey}-sign-out`}
                />
            </View>
            {switchFailed ? (
                <View style={styles.failure} accessibilityRole="alert">
                    <Text style={styles.failureText}>Couldn't switch to {label}.</Text>
                    <AccountActionButton
                        label="Try again"
                        onPress={onRetrySwitch}
                        disabled={disabled}
                        testID={`settings-account-${testKey}-retry`}
                    />
                </View>
            ) : null}
            {confirmingSignOut ? (
                <SignOutConfirm
                    from="settings"
                    target={account.key}
                    pending={signOutPending}
                    error={signOutError}
                    onCancel={onCancelSignOut}
                    onConfirm={onConfirmSignOut}
                    style={styles.confirm}
                    testIDPrefix={`settings-account-${testKey}`}
                />
            ) : null}
        </View>
    )
}

const useStyles = createStyles(({ colors }) => ({
    row: {
        flexDirection: 'row',
        alignItems: 'center',
        gap: 8,
        paddingRight: 12,
    },
    main: {
        flex: 1,
        minWidth: 0,
        minHeight: 64,
        flexDirection: 'row',
        alignItems: 'center',
        gap: 12,
        paddingVertical: 10,
        paddingLeft: 16,
    },
    warn: {
        ...type.meta,
        color: colors.orange,
        flexShrink: 0,
    },
    activeStatus: {
        flexDirection: 'row',
        alignItems: 'center',
        gap: 3,
        flexShrink: 0,
    },
    activeText: {
        ...type.meta,
        color: colors.secondary,
    },
    failure: {
        flexDirection: 'row',
        alignItems: 'center',
        gap: 12,
        paddingLeft: 16,
        paddingRight: 12,
        paddingBottom: 12,
    },
    failureText: {
        ...type.metaSmall,
        color: colors.muted,
        flex: 1,
    },
    confirm: {
        paddingHorizontal: 16,
        paddingTop: 4,
        paddingBottom: 16,
    },
}))
