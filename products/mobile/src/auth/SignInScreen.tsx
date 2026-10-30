import { getCalendars, getLocales } from 'expo-localization'
import { useRouter } from 'expo-router'
import { type ReactElement, useState } from 'react'
import { ActivityIndicator, Linking, ScrollView, Text, View } from 'react-native'

import { useDemoMode } from '@/demo/demoMode'
import { currentDefaultPageHref, defaultPageHref, settleDefaultPage } from '@/features/settings/defaultPageStore'
import { track } from '@/lib/analytics'
import { toError } from '@/lib/errors'
import { openLegalLink, PRIVACY_POLICY_URL, TERMS_URL } from '@/lib/legalLinks'
import { useAsyncAction } from '@/lib/useAsyncAction'
import { EnvironmentRibbon } from '@/ui/EnvironmentRibbon'
import { PostHogLogo } from '@/ui/icons/PostHogLogo'
import { Pressable44 } from '@/ui/Pressable44'
import { createStyles, useColors } from '@/ui/theme'
import { layout, radii, type } from '@/ui/tokens'
import { bottomOffset, useScreenInsets } from '@/ui/useScreenInsets'

import { useAuthStore } from './authStore'
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
import { signInFailureReason } from './signInErrors'

export function SignInScreen(): ReactElement {
    const colors = useColors()
    const styles = useStyles()
    const router = useRouter()
    const insets = useScreenInsets()
    const signIn = useAuthStore((state) => state.signIn)
    const signedOutReason = useAuthStore((state) => state.signedOutReason)
    const setDemo = useDemoMode((state) => state.setEnabled)
    const [cloudRegion, setCloudRegion] = useState<CloudRegion['id']>(() => {
        const { region, host } = useAuthStore.getState()
        return defaultCloudRegion(
            getLocales()[0]?.regionCode ?? null,
            getCalendars()[0]?.timeZone ?? null,
            host ? region : undefined
        )
    })
    const [selfHosted, setSelfHosted] = useState(() => useAuthStore.getState().region === 'custom')
    const region: RegionId = selfHosted ? 'custom' : cloudRegion
    const [customHost, setCustomHost] = useState(() => {
        const { region: lastRegion, host } = useAuthStore.getState()
        return lastRegion === 'custom' && host ? host : ''
    })
    const [clientId, setClientId] = useState(() => {
        const { region: lastRegion, clientId: lastClientId } = useAuthStore.getState()
        return lastRegion === 'custom' && lastClientId ? lastClientId : DEFAULT_CUSTOM_CLIENT_ID
    })
    const [error, setError] = useState<{ message: string; retryable: boolean } | null>(null)

    const selected = CLOUD_REGIONS.find((option) => option.id === cloudRegion)
    const customHostCheck = selfHosted ? validateHost(customHost) : null
    const formHost = customHostCheck ? (customHostCheck.ok ? customHostCheck.host : null) : (selected?.host ?? null)

    const submit = useAsyncAction(async () => {
        setError(null)
        const host = selfHosted ? customHost : (selected?.host ?? '')
        const method = 'oauth'
        track('mobile_sign_in_started', { method, region, after_expiry: signedOutReason === 'expired' })
        try {
            await signIn(host, selfHosted ? clientId : (selected?.clientId ?? ''))
            if (useDemoMode.getState().enabled) {
                track('mobile_demo_ended', { from: 'sign_in' })
            }
            setDemo(false)
            router.replace(defaultPageHref(settleDefaultPage()))
        } catch (caught) {
            // Retrying cannot help when this platform has no OAuth sign-in.
            const retryable = !(caught instanceof OAuthError && caught.kind === 'unsupported')
            track('mobile_sign_in_failed', {
                method,
                region,
                reason: signInFailureReason(caught, method),
                retryable,
            })
            setError({ message: toError(caught).message, retryable })
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

    return (
        <ScrollView
            style={styles.screen}
            contentContainerStyle={[
                styles.content,
                { paddingTop: insets.top, paddingBottom: bottomOffset(insets, 38) },
            ]}
            keyboardShouldPersistTaps="handled"
            automaticallyAdjustKeyboardInsets
            testID="sign-in-screen"
        >
            <View style={styles.main}>
                <EnvironmentRibbon host={formHost} style={styles.ribbon} />
                <View style={styles.brand}>
                    <PostHogLogo height={28} />
                </View>
                <View style={styles.card}>
                    <View style={styles.titleRow}>
                        <Text style={styles.title}>Log in to </Text>
                        <Text style={[styles.title, styles.titleChip]}>@PostHog</Text>
                    </View>
                    <Text style={styles.sub}>Let's go ship something.</Text>
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
                        {signedOutReason === 'expired' && !error ? (
                            <Text style={styles.notice} testID="sign-in-expired">
                                Your session ended. Log in again to continue.
                            </Text>
                        ) : null}
                        {error ? (
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
                </View>
                {SHOW_SIGNUP_LINK && !selfHosted ? (
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
            </View>
            <View style={styles.legal}>
                <Pressable44
                    onPress={() => openLegalLink('privacy', PRIVACY_POLICY_URL, 'sign_in')}
                    accessibilityRole="link"
                    pressedBackground={colors.pressed}
                    style={styles.legalLink}
                    testID="sign-in-privacy"
                >
                    <Text style={styles.legalText}>Privacy policy</Text>
                </Pressable44>
                <Text style={styles.legalText} importantForAccessibility="no" accessibilityElementsHidden>
                    ·
                </Text>
                <Pressable44
                    onPress={() => openLegalLink('terms', TERMS_URL, 'sign_in')}
                    accessibilityRole="link"
                    pressedBackground={colors.pressed}
                    style={styles.legalLink}
                    testID="sign-in-terms"
                >
                    <Text style={styles.legalText}>Terms</Text>
                </Pressable44>
            </View>
        </ScrollView>
    )
}

const useStyles = createStyles(({ colors }) => ({
    screen: {
        flex: 1,
        backgroundColor: colors.background,
    },
    content: {
        flexGrow: 1,
        paddingHorizontal: layout.detailGutter,
    },
    main: {
        flexGrow: 1,
        justifyContent: 'center',
        paddingVertical: 24,
    },
    ribbon: {
        alignSelf: 'center',
        marginBottom: 24,
    },
    brand: {
        alignItems: 'center',
        marginBottom: 28,
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
    legal: {
        marginTop: 12,
        flexDirection: 'row',
        alignItems: 'center',
        justifyContent: 'center',
        gap: 4,
    },
    legalLink: {
        minHeight: 44,
        paddingHorizontal: 8,
        borderRadius: radii.card,
        alignItems: 'center',
        justifyContent: 'center',
    },
    legalText: {
        ...type.meta,
        color: colors.secondary,
    },
}))
