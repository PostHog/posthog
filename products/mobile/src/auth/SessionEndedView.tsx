import { type ReactElement, useEffect, useState } from 'react'
import { ActivityIndicator, Text, View } from 'react-native'

import { AccountActionButton } from '@/features/accounts/AccountActionButton'
import { AccountIdentity } from '@/features/accounts/AccountIdentity'
import { accountLabel, nextAccountAfterSignOut } from '@/features/accounts/accountLabel'
import { postAccountNotice } from '@/features/accounts/accountNotices'
import { useAccountSwitch } from '@/features/accounts/useAccountSwitch'
import { SignOutConfirm } from '@/features/settings/SignOutConfirm'
import { track } from '@/lib/analytics'
import { toError } from '@/lib/errors'
import { useAsyncAction } from '@/lib/useAsyncAction'
import { ChevronRightIcon } from '@/ui/icons/ChevronRightIcon'
import { Pressable44 } from '@/ui/Pressable44'
import { createStyles, useColors } from '@/ui/theme'
import { radii, type } from '@/ui/tokens'

import { AccountNeedsSignInError, type StoredAccount, useAuthStore } from './authStore'
import { SignInFrame } from './SignInFrame'

interface SessionEndedViewProps {
    /** The account whose session expired. It stays on the phone until a new sign-in or a sign out. */
    account: StoredAccount
    onSignInAgain: () => void
}

/** The sign-in screen after an expiry: names the account, and offers its sign-in, the other accounts, or a sign out. */
export function SessionEndedView({ account, onSignInAgain }: SessionEndedViewProps): ReactElement {
    const colors = useColors()
    const styles = useStyles()
    const accounts = useAuthStore((state) => state.accounts)
    const others = accounts.filter((candidate) => candidate.key !== account.key && !candidate.needsSignIn)
    const accountSwitch = useAccountSwitch('sign_in')
    const [confirming, setConfirming] = useState(false)
    const [signOutError, setSignOutError] = useState<string | null>(null)
    const busy = accountSwitch.pending !== null

    // biome-ignore lint/correctness/useExhaustiveDependencies: one event per expired account shown.
    useEffect(() => {
        track('mobile_session_ended_shown', { account_count: accounts.length, other_accounts: others.length })
    }, [account.key])

    // The store removes only this account. While signed out no account is active, so this switches to the next one.
    const signOut = useAsyncAction(async () => {
        setSignOutError(null)
        const left = accountLabel(account, accounts)
        try {
            await useAuthStore.getState().signOutAccount(account.key)
            const tried = new Set([account.key])
            let next = nextAccountAfterSignOut(useAuthStore.getState().accounts, account.key)
            while (next && !tried.has(next.key)) {
                tried.add(next.key)
                try {
                    await useAuthStore.getState().switchAccount(next.key, { from: 'sign_out' })
                    break
                } catch (error) {
                    if (!(error instanceof AccountNeedsSignInError)) {
                        throw error
                    }
                    // The store marked it as needing a sign-in, so the next candidate is another account.
                    next = nextAccountAfterSignOut(useAuthStore.getState().accounts, account.key)
                }
            }
            const { activeAccountKey, status } = useAuthStore.getState()
            if (next && activeAccountKey === next.key && status === 'signed_in') {
                postAccountNotice({ kind: 'signed_out', left })
            }
        } catch (error) {
            setSignOutError(toError(error).message)
        }
    })

    const signInAgain = (): void => {
        track('mobile_session_ended_action', { action: 'sign_in_again' })
        onSignInAgain()
    }
    const switchTo = (key: string): void => {
        track('mobile_session_ended_action', { action: 'switch' })
        void accountSwitch.run({ key })
    }

    return (
        <SignInFrame ribbonHost={account.host} testID="session-ended-screen">
            <View style={styles.card}>
                <View style={styles.identity}>
                    <AccountIdentity account={account} size="large" />
                </View>
                <Text style={styles.heading} accessibilityRole="header">
                    Your session ended
                </Text>
                <Text style={styles.body}>
                    {others.length > 0
                        ? 'Sign in again to keep using this account. Your other accounts stay signed in.'
                        : 'Sign in again to keep using this account.'}
                </Text>
                <View style={styles.primary}>
                    <Pressable44
                        onPress={signInAgain}
                        disabled={busy || signOut.pending}
                        pressedBackground={colors.accentHover}
                        style={styles.primaryPressable}
                        testID="session-ended-sign-in"
                    >
                        <Text style={styles.primaryText}>Sign in again</Text>
                    </Pressable44>
                </View>
                {others.length > 0 ? (
                    <>
                        <View style={styles.divider} />
                        <Text style={[type.eyebrow, styles.eyebrow]}>OR SWITCH TO</Text>
                        {others.map((other) => {
                            const switching = accountSwitch.pending?.key === other.key
                            return (
                                <View key={other.key}>
                                    <Pressable44
                                        onPress={() => switchTo(other.key)}
                                        disabled={busy || signOut.pending}
                                        accessibilityLabel={`Switch to ${accountLabel(other, accounts)}`}
                                        accessibilityState={{ busy: switching, disabled: busy || signOut.pending }}
                                        pressedBackground={colors.background}
                                        style={styles.row}
                                        testID={`session-ended-switch-${other.key}`}
                                    >
                                        <AccountIdentity account={other} size="regular" />
                                        {switching ? (
                                            <ActivityIndicator color={colors.ink} accessibilityLabel="Switching" />
                                        ) : (
                                            <ChevronRightIcon size={15} color={colors.tertiary} />
                                        )}
                                    </Pressable44>
                                    {accountSwitch.failed?.key === other.key ? (
                                        <View style={styles.failure} accessibilityRole="alert">
                                            <Text style={styles.failureText}>
                                                Couldn't switch to {accountLabel(other, accounts)}.
                                            </Text>
                                            <AccountActionButton
                                                label="Try again"
                                                onPress={() => switchTo(other.key)}
                                                disabled={busy || signOut.pending}
                                                testID={`session-ended-retry-${other.key}`}
                                            />
                                        </View>
                                    ) : null}
                                </View>
                            )
                        })}
                    </>
                ) : null}
                {confirming ? (
                    <SignOutConfirm
                        from="session_ended"
                        target={account.key}
                        pending={signOut.pending}
                        error={signOutError}
                        onCancel={() => {
                            setSignOutError(null)
                            setConfirming(false)
                        }}
                        onConfirm={() => void signOut.run()}
                        style={styles.confirm}
                        testIDPrefix="session-ended"
                    />
                ) : (
                    <Pressable44
                        onPress={() => {
                            track('mobile_session_ended_action', { action: 'sign_out' })
                            setConfirming(true)
                        }}
                        disabled={busy}
                        pressedStyle={styles.linkPressed}
                        style={styles.link}
                        testID="session-ended-sign-out"
                    >
                        <Text style={styles.linkText}>Sign out of this account</Text>
                    </Pressable44>
                )}
            </View>
        </SignInFrame>
    )
}

const useStyles = createStyles(({ colors }) => ({
    card: {
        backgroundColor: colors.surface,
        borderRadius: radii.softCard,
        borderWidth: 1,
        borderColor: colors.hairline,
        padding: 24,
    },
    identity: {
        flexDirection: 'row',
        paddingBottom: 20,
        marginBottom: 20,
        borderBottomWidth: 1,
        borderBottomColor: colors.hairline,
    },
    heading: {
        ...type.headline,
        color: colors.ink,
    },
    body: {
        ...type.body,
        color: colors.muted,
        marginTop: 8,
    },
    primary: {
        marginTop: 20,
        height: 52,
        borderRadius: radii.card,
        backgroundColor: colors.accent,
        overflow: 'hidden',
    },
    primaryPressable: {
        flex: 1,
        alignItems: 'center',
        justifyContent: 'center',
    },
    primaryText: {
        ...type.button,
        color: colors.onAccent,
    },
    divider: {
        marginVertical: 20,
        borderTopWidth: 1,
        borderStyle: 'dashed',
        borderColor: colors.border,
    },
    eyebrow: {
        color: colors.tertiary,
        paddingHorizontal: 4,
        marginBottom: 4,
    },
    row: {
        minHeight: 60,
        flexDirection: 'row',
        alignItems: 'center',
        gap: 12,
        paddingVertical: 8,
        paddingHorizontal: 4,
        borderRadius: radii.card,
    },
    failure: {
        flexDirection: 'row',
        alignItems: 'center',
        gap: 12,
        paddingHorizontal: 4,
        paddingBottom: 8,
    },
    failureText: {
        ...type.metaSmall,
        color: colors.muted,
        flex: 1,
    },
    confirm: {
        marginTop: 16,
    },
    link: {
        height: 44,
        marginTop: 6,
        alignSelf: 'center',
        alignItems: 'center',
        justifyContent: 'center',
    },
    linkPressed: {
        opacity: 0.6,
    },
    linkText: {
        ...type.buttonSmall,
        color: colors.secondary,
    },
}))
