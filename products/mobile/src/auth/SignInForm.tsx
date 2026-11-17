import { getCalendars, getLocales } from 'expo-localization'
import { useLocalSearchParams, useRouter } from 'expo-router'
import { type ReactElement, useEffect, useRef, useState } from 'react'
import { ActivityIndicator, Linking, Text, View } from 'react-native'

import { useDemoMode } from '@/demo/demoMode'
import { accountLabel } from '@/features/accounts/accountLabel'
import { postAccountNotice } from '@/features/accounts/accountNotices'
import { currentDefaultPageHref } from '@/features/settings/defaultPageStore'
import { track } from '@/lib/analytics'
import { toError } from '@/lib/errors'
import { useAsyncAction } from '@/lib/useAsyncAction'
import { Pressable44 } from '@/ui/Pressable44'
import { createStyles, useColors, useTheme } from '@/ui/theme'
import { radii, type } from '@/ui/tokens'

import { AccountAlreadyAddedNotice } from './AccountAlreadyAddedNotice'
import { type StoredAccount, useAuthStore } from './authStore'
import { OAuthError } from './oauth'
import { RegionSelect } from './RegionSelect'
import {
    CLOUD_REGIONS,
    type CloudRegion,
    DEFAULT_CUSTOM_CLIENT_ID,
    defaultCloudRegion,
    type RegionId,
    SHOW_SIGNUP_LINK,
    signupUrl,
    validateHost,
} from './regions'
import { SignInField } from './SignInField'
import { SignInFrame } from './SignInFrame'
import { AccountAlreadyAddedError, signInFailureReason } from './signInErrors'
import { signInReturnFor, signInReturnParam } from './signInReturn'

interface SignInFormProps {
    /** `add` signs in to another account while one is active, or signs `reauth` in again. */
    mode: 'sign_in' | 'add'
    /** A stored account that needs a new sign-in. The form starts on its host. */
    reauth: StoredAccount | null
    /** Shown as Cancel above the logo in add mode. */
    onCancel: (() => void) | null
}

interface FormError {
    message: string
    retryable: boolean
    alreadyAdded: AccountAlreadyAddedError | null
}

function initialCloudRegion(reauth: StoredAccount | null): CloudRegion['id'] {
    if (reauth && reauth.region !== 'custom') {
        return reauth.region
    }
    const { region, host } = useAuthStore.getState()
    return defaultCloudRegion(
        getLocales()[0]?.regionCode ?? null,
        getCalendars()[0]?.timeZone ?? null,
        host ? region : undefined
    )
}

export function SignInForm({ mode, reauth, onCancel }: SignInFormProps): ReactElement {
    const colors = useColors()
    const { shadows } = useTheme()
    const styles = useStyles()
    const router = useRouter()
    const returnParams = useLocalSearchParams<{ next?: string; account?: string }>()
    const returnTo = signInReturnParam(returnParams.next)
    const signIn = useAuthStore((state) => state.signIn)
    const signedOutReason = useAuthStore((state) => state.signedOutReason)
    const accounts = useAuthStore((state) => state.accounts)
    const setDemo = useDemoMode((state) => state.setEnabled)
    const adding = mode === 'add'
    const analyticsMode = reauth ? 'reauth' : mode
    const [cloudRegion, setCloudRegion] = useState<CloudRegion['id']>(() => initialCloudRegion(reauth))
    const [selfHosted, setSelfHosted] = useState(() =>
        reauth ? reauth.region === 'custom' : useAuthStore.getState().region === 'custom'
    )
    const region: RegionId = selfHosted ? 'custom' : cloudRegion
    const [customHost, setCustomHost] = useState(() => {
        if (reauth) {
            return reauth.region === 'custom' ? reauth.host : ''
        }
        const { region: lastRegion, host } = useAuthStore.getState()
        return lastRegion === 'custom' && host ? host : ''
    })
    const [clientId, setClientId] = useState(() => {
        if (reauth?.region === 'custom' && reauth.clientId) {
            return reauth.clientId
        }
        const { region: lastRegion, clientId: lastClientId } = useAuthStore.getState()
        return lastRegion === 'custom' && lastClientId ? lastClientId : DEFAULT_CUSTOM_CLIENT_ID
    })
    const [error, setError] = useState<FormError | null>(null)
    // A sign-in that adds an account remounts every screen on the start page, so this screen must not navigate then.
    const mounted = useRef(true)
    useEffect(
        () => () => {
            mounted.current = false
        },
        []
    )

    const selected = CLOUD_REGIONS.find((option) => option.id === cloudRegion)
    const customHostCheck = selfHosted ? validateHost(customHost) : null
    const formHost = customHostCheck ? (customHostCheck.ok ? customHostCheck.host : null) : (selected?.host ?? null)
    const otherAccounts = accounts.some((account) => account.key !== reauth?.key && !account.needsSignIn)

    const submit = useAsyncAction(async () => {
        setError(null)
        const host = selfHosted ? customHost : (selected?.host ?? '')
        const method = 'oauth'
        const before = useAuthStore.getState()
        const knownKeys = new Set(before.accounts.map((account) => account.key))
        track('mobile_sign_in_started', {
            method,
            region,
            mode: analyticsMode,
            after_expiry: signedOutReason === 'expired',
        })
        try {
            await signIn(host, selfHosted ? clientId : (selected?.clientId ?? ''), { reauth: reauth?.key })
            if (useDemoMode.getState().enabled) {
                track('mobile_demo_ended', { from: 'sign_in' })
            }
            setDemo(false)
            const { activeAccountKey } = useAuthStore.getState()
            if (activeAccountKey && knownKeys.size > 0 && !knownKeys.has(activeAccountKey)) {
                postAccountNotice({ kind: 'added' })
            } else if (before.activeAccountKey && activeAccountKey !== before.activeAccountKey) {
                postAccountNotice({ kind: 'switched' })
            }
            if (mounted.current) {
                router.replace(
                    signInReturnFor(returnTo, returnParams.account, activeAccountKey) ?? currentDefaultPageHref()
                )
            }
        } catch (caught) {
            // Retrying cannot help when this platform has no OAuth sign-in.
            const retryable = !(caught instanceof OAuthError && caught.kind === 'unsupported')
            track('mobile_sign_in_failed', {
                method,
                region,
                mode: analyticsMode,
                reason: signInFailureReason(caught, method),
                retryable,
            })
            setError({
                message: toError(caught).message,
                retryable,
                alreadyAdded: caught instanceof AccountAlreadyAddedError ? caught : null,
            })
        }
    })

    const changeRegion = (next: RegionId): void => {
        if (next !== region) {
            track('mobile_sign_in_region_changed', { region: next })
        }
        setError(null)
        setSelfHosted(next === 'custom')
        if (next !== 'custom') {
            setCloudRegion(next)
        }
    }

    const tryDemo = (): void => {
        track('mobile_demo_started', { from: 'sign_in' })
        setDemo(true)
        router.replace(currentDefaultPageHref())
    }

    const createAccount = (): void => {
        if (!selected?.host) {
            return
        }
        track('mobile_create_account_opened', { region })
        Linking.openURL(signupUrl(selected.host)).catch(() => undefined)
    }

    const subtitle = reauth
        ? otherAccounts
            ? 'Your other accounts stay signed in.'
            : "Let's go ship something."
        : adding
          ? 'Add another account to this phone.'
          : "Let's go ship something."

    return (
        <SignInFrame
            ribbonHost={formHost}
            testID="sign-in-screen"
            top={
                onCancel ? (
                    <View style={styles.top}>
                        <Pressable44
                            onPress={onCancel}
                            disabled={submit.pending}
                            style={[styles.cancel, shadows.chip]}
                            pressedStyle={styles.cancelPressed}
                            testID="sign-in-cancel"
                        >
                            <Text style={styles.cancelText}>Cancel</Text>
                        </Pressable44>
                    </View>
                ) : null
            }
        >
            <View style={styles.card}>
                <View style={styles.titleRow}>
                    <Text style={styles.title}>Log in to </Text>
                    <Text style={[styles.title, styles.titleChip]}>@PostHog</Text>
                </View>
                <Text style={styles.sub}>{subtitle}</Text>
                <View style={styles.form}>
                    {selfHosted ? (
                        <>
                            <SignInField
                                label="Host"
                                value={customHost}
                                onChangeText={setCustomHost}
                                placeholder="posthog.example.com"
                                keyboardType="url"
                                editable={!submit.pending}
                                testID="sign-in-host"
                            />
                            <SignInField
                                label="Client ID"
                                value={clientId}
                                onChangeText={setClientId}
                                placeholder="OAuth client ID"
                                hint="The client ID of the PostHog mobile app registered on this instance."
                                editable={!submit.pending}
                                testID="sign-in-client-id"
                            />
                        </>
                    ) : (
                        <View style={styles.field}>
                            <Text style={[type.eyebrow, styles.label]}>DATA REGION</Text>
                            <RegionSelect value={cloudRegion} onChange={changeRegion} disabled={submit.pending} />
                        </View>
                    )}
                    {reauth && !error ? (
                        <Text style={styles.notice} testID="sign-in-reauth">
                            Sign in again to use {accountLabel(reauth, accounts)}.
                        </Text>
                    ) : null}
                    {!adding && signedOutReason === 'expired' && !error ? (
                        <Text style={styles.notice} testID="sign-in-expired">
                            Your session ended. Log in again to continue.
                        </Text>
                    ) : null}
                    {error?.alreadyAdded ? (
                        <AccountAlreadyAddedNotice
                            error={error.alreadyAdded}
                            pending={submit.pending}
                            onRetry={() => void submit.run()}
                        />
                    ) : error ? (
                        <View style={styles.errorBox} testID="sign-in-error">
                            <Text style={styles.errorText}>{error.message}</Text>
                            {error.retryable ? (
                                <Pressable44
                                    onPress={() => void submit.run()}
                                    disabled={submit.pending}
                                    pressedBackground={colors.sunken}
                                    style={styles.retry}
                                    testID="sign-in-retry"
                                >
                                    <Text style={styles.retryText}>Try again</Text>
                                </Pressable44>
                            ) : null}
                        </View>
                    ) : null}
                </View>
                <View style={[styles.primary, submit.pending && styles.primaryPending]}>
                    <Pressable44
                        onPress={() => void submit.run()}
                        disabled={submit.pending}
                        accessibilityState={{ busy: submit.pending, disabled: submit.pending }}
                        pressedBackground={colors.accentHover}
                        style={styles.primaryPressable}
                        testID="sign-in"
                    >
                        {submit.pending ? (
                            <ActivityIndicator color={colors.onAccent} />
                        ) : (
                            <Text style={styles.primaryText}>Log in</Text>
                        )}
                    </Pressable44>
                </View>
                {reauth ? null : (
                    <View style={styles.links}>
                        <Pressable44
                            onPress={() => changeRegion(selfHosted ? cloudRegion : 'custom')}
                            disabled={submit.pending}
                            pressedStyle={styles.linkPressed}
                            style={styles.link}
                            testID="sign-in-self-hosted"
                        >
                            <Text style={styles.linkText}>
                                {selfHosted ? 'Use PostHog Cloud instead' : 'Use a self-hosted instance'}
                            </Text>
                        </Pressable44>
                    </View>
                )}
                {adding ? null : (
                    <>
                        <View style={styles.divider} />
                        <Pressable44
                            onPress={tryDemo}
                            disabled={submit.pending}
                            pressedBackground={colors.sunken}
                            style={styles.secondary}
                            testID="try-demo"
                        >
                            <Text style={styles.secondaryText}>Try the demo</Text>
                        </Pressable44>
                    </>
                )}
            </View>
            {SHOW_SIGNUP_LINK && !selfHosted && !reauth ? (
                <Pressable44
                    onPress={createAccount}
                    disabled={submit.pending}
                    accessibilityRole="link"
                    pressedBackground={colors.pressed}
                    style={styles.footer}
                    testID="create-account"
                >
                    <Text style={styles.footerText}>
                        New to PostHog? <Text style={styles.footerLink}>Create an account →</Text>
                    </Text>
                </Pressable44>
            ) : null}
        </SignInFrame>
    )
}

const useStyles = createStyles(({ colors }) => ({
    // The prototype's 50pt row ends 4pt below the 46pt chip, at the same place as the Back chip on pushed pages.
    top: {
        height: 50,
        width: '100%',
        maxWidth: 600,
        alignSelf: 'center',
        justifyContent: 'flex-end',
        alignItems: 'flex-start',
    },
    // 44pt content box plus a 1pt border on each side, like the Back chip.
    cancel: {
        height: 46,
        paddingHorizontal: 18,
        borderRadius: radii.pill,
        backgroundColor: colors.surface,
        borderWidth: 1,
        borderColor: colors.border,
        alignItems: 'center',
        justifyContent: 'center',
    },
    cancelPressed: {
        borderColor: colors.disabled,
    },
    cancelText: {
        ...type.buttonSmall,
        color: colors.ink,
    },
    card: {
        backgroundColor: colors.surface,
        borderRadius: radii.softCard,
        borderWidth: 1,
        borderColor: colors.hairline,
        padding: 24,
    },
    titleRow: {
        flexDirection: 'row',
        alignItems: 'center',
        justifyContent: 'center',
    },
    title: {
        ...type.headline,
        color: colors.ink,
    },
    titleChip: {
        color: colors.blue,
        backgroundColor: colors.blueHighlight,
        borderRadius: radii.markSmall,
        paddingHorizontal: 6,
        overflow: 'hidden',
    },
    sub: {
        ...type.body,
        color: colors.muted,
        textAlign: 'center',
        marginTop: 6,
    },
    form: {
        marginTop: 28,
        gap: 16,
    },
    field: {
        gap: 8,
    },
    label: {
        color: colors.tertiary,
        paddingHorizontal: 4,
    },
    notice: {
        ...type.metaSmall,
        color: colors.muted,
        paddingHorizontal: 4,
    },
    errorBox: {
        gap: 10,
        alignItems: 'flex-start',
        padding: 12,
        borderRadius: radii.card,
        backgroundColor: colors.sunken,
    },
    errorText: {
        ...type.metaSmall,
        color: colors.ink,
    },
    retry: {
        height: 36,
        paddingHorizontal: 14,
        borderRadius: radii.pill,
        borderWidth: 1,
        borderColor: colors.border,
        backgroundColor: colors.surface,
        alignItems: 'center',
        justifyContent: 'center',
    },
    retryText: {
        ...type.buttonSmall,
        color: colors.ink,
    },
    primary: {
        marginTop: 20,
        height: 52,
        borderRadius: radii.card,
        backgroundColor: colors.accent,
        overflow: 'hidden',
    },
    primaryPending: {
        opacity: 0.8,
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
    secondary: {
        height: 48,
        borderRadius: radii.card,
        borderWidth: 1,
        borderColor: colors.border,
        backgroundColor: colors.surface,
        alignItems: 'center',
        justifyContent: 'center',
    },
    secondaryText: {
        ...type.button,
        color: colors.ink,
    },
    links: {
        marginTop: 6,
    },
    link: {
        height: 44,
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
    footer: {
        marginTop: 20,
        minHeight: 44,
        borderRadius: radii.card,
        alignItems: 'center',
        justifyContent: 'center',
        paddingHorizontal: 12,
    },
    footerText: {
        ...type.metaSmall,
        color: colors.muted,
        textAlign: 'center',
    },
    footerLink: {
        ...type.bodySmallStrong,
        fontSize: 14,
        color: colors.ink,
    },
}))
