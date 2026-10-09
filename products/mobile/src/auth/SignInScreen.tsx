import { useRouter } from 'expo-router'
import { type ReactElement, useState } from 'react'
import { ActivityIndicator, ScrollView, StyleSheet, Text, View } from 'react-native'

import { useDemoMode } from '@/demo/demoMode'
import { toError } from '@/lib/errors'
import { useAsyncAction } from '@/lib/useAsyncAction'
import { LogoMark } from '@/ui/icons/LogoMark'
import { Pressable44 } from '@/ui/Pressable44'
import { SegmentedPill } from '@/ui/SegmentedPill'
import { colors, layout, radii, type } from '@/ui/tokens'
import { bottomOffset, topOffset, useScreenInsets } from '@/ui/useScreenInsets'

import { useAuthStore } from './authStore'
import { OAuthError } from './oauth'
import { DEV_CLIENT_ID, REGIONS, type RegionId } from './regions'
import { SignInField } from './SignInField'

type SignInMode = 'oauth' | 'personal_api_key'

export function SignInScreen(): ReactElement {
    const router = useRouter()
    const insets = useScreenInsets()
    const signIn = useAuthStore((state) => state.signIn)
    const signInWithPersonalApiKey = useAuthStore((state) => state.signInWithPersonalApiKey)
    const signedOutReason = useAuthStore((state) => state.signedOutReason)
    const setDemo = useDemoMode((state) => state.setEnabled)
    // The last sign-in's region, host and client id survive sign out, so the form starts there.
    const [region, setRegion] = useState<RegionId>(() => useAuthStore.getState().region)
    const [customHost, setCustomHost] = useState(() => {
        const { region: lastRegion, host } = useAuthStore.getState()
        return lastRegion === 'custom' && host ? host : ''
    })
    const [clientId, setClientId] = useState(() => {
        const { region: lastRegion, clientId: lastClientId } = useAuthStore.getState()
        return lastRegion === 'custom' && lastClientId ? lastClientId : DEV_CLIENT_ID
    })
    const [mode, setMode] = useState<SignInMode>('oauth')
    const [apiKey, setApiKey] = useState('')
    const [error, setError] = useState<{ message: string; retryable: boolean } | null>(null)

    const selected = REGIONS.find((option) => option.id === region)
    const usingKey = __DEV__ && mode === 'personal_api_key'

    const submit = useAsyncAction(async () => {
        setError(null)
        const host = region === 'custom' ? customHost : (selected?.host ?? '')
        try {
            if (usingKey) {
                await signInWithPersonalApiKey(host, apiKey)
            } else {
                await signIn(host, region === 'custom' ? clientId : (selected?.clientId ?? ''))
            }
            setDemo(false)
            router.replace('/inbox')
        } catch (caught) {
            // Retrying cannot help when this platform has no OAuth sign-in.
            const retryable = !(caught instanceof OAuthError && caught.kind === 'unsupported')
            setError({ message: toError(caught).message, retryable })
        }
    })

    const tryDemo = (): void => {
        setDemo(true)
        router.replace('/inbox')
    }

    return (
        <ScrollView
            style={styles.screen}
            contentContainerStyle={[
                styles.content,
                { paddingTop: topOffset(insets, 120), paddingBottom: bottomOffset(insets, 38) },
            ]}
            keyboardShouldPersistTaps="handled"
            automaticallyAdjustKeyboardInsets
            testID="sign-in-screen"
        >
            <View style={styles.intro}>
                <LogoMark variant="large" />
                <Text style={styles.title} accessibilityRole="header">
                    PostHog
                </Text>
                <Text style={styles.sub}>Triage your inbox and hand reports to the PostHog agent.</Text>
            </View>
            <View style={styles.form}>
                <Text style={[type.eyebrow, styles.eyebrow]}>REGION</Text>
                <SegmentedPill
                    height={48}
                    segments={REGIONS.map((option) => ({
                        key: option.id,
                        accessibilityLabel: option.id === 'custom' ? 'Custom host' : `${option.label} cloud`,
                        selected: region === option.id,
                        disabled: submit.pending,
                        onPress: () => setRegion(option.id),
                        testID: `region-${option.id}`,
                        children: <Text style={styles.segmentText}>{option.label}</Text>,
                    }))}
                />
                {region === 'custom' ? (
                    <View style={styles.fields}>
                        <SignInField
                            label="Host"
                            value={customHost}
                            onChangeText={setCustomHost}
                            placeholder="posthog.example.com"
                            keyboardType="url"
                            editable={!submit.pending}
                            testID="sign-in-host"
                        />
                        {usingKey ? null : (
                            <SignInField
                                label="Client ID"
                                value={clientId}
                                onChangeText={setClientId}
                                placeholder="OAuth client ID"
                                hint="The client ID of the PostHog mobile app registered on this instance."
                                editable={!submit.pending}
                                testID="sign-in-client-id"
                            />
                        )}
                    </View>
                ) : null}
                {usingKey ? (
                    <View style={styles.fields}>
                        <SignInField
                            label="Personal API key"
                            value={apiKey}
                            onChangeText={setApiKey}
                            placeholder="phx_..."
                            secret
                            hint="Development builds only. The key needs user:read, organization:read and project:read."
                            editable={!submit.pending}
                            testID="sign-in-api-key"
                        />
                    </View>
                ) : null}
                {signedOutReason === 'expired' && !error ? (
                    <Text style={styles.notice} testID="sign-in-expired">
                        Your session ended. Sign in again to continue.
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
            <View style={styles.actions}>
                <View style={[styles.primary, submit.pending && styles.primaryPending]}>
                    <Pressable44
                        onPress={() => void submit.run()}
                        disabled={submit.pending}
                        accessibilityState={{ busy: submit.pending, disabled: submit.pending }}
                        pressedBackground={colors.pressOverlay}
                        style={styles.primaryPressable}
                        testID="sign-in"
                    >
                        {submit.pending ? (
                            <ActivityIndicator color={colors.white} />
                        ) : (
                            <Text style={styles.primaryText}>{usingKey ? 'Sign in with key' : 'Sign in'}</Text>
                        )}
                    </Pressable44>
                </View>
                <Pressable44
                    onPress={tryDemo}
                    disabled={submit.pending}
                    pressedBackground={colors.sunken}
                    style={styles.secondary}
                    testID="try-demo"
                >
                    <Text style={styles.secondaryText}>Try the demo</Text>
                </Pressable44>
                {__DEV__ ? (
                    <Pressable44
                        onPress={() => {
                            setError(null)
                            setMode(usingKey ? 'oauth' : 'personal_api_key')
                        }}
                        disabled={submit.pending}
                        pressedBackground={colors.sunken}
                        style={styles.link}
                        testID="sign-in-mode"
                    >
                        <Text style={styles.linkText}>
                            {usingKey ? 'Sign in with PostHog instead' : 'Use a personal API key'}
                        </Text>
                    </Pressable44>
                ) : null}
            </View>
        </ScrollView>
    )
}

const styles = StyleSheet.create({
    screen: {
        flex: 1,
        backgroundColor: colors.background,
    },
    content: {
        flexGrow: 1,
        paddingHorizontal: layout.detailGutter,
    },
    intro: {
        alignItems: 'flex-start',
    },
    title: {
        ...type.screenTitle,
        color: colors.ink,
        marginTop: 16,
    },
    sub: {
        ...type.body,
        color: colors.muted,
        marginTop: 8,
    },
    form: {
        marginTop: 36,
        gap: 10,
    },
    fields: {
        marginTop: 8,
        gap: 14,
    },
    eyebrow: {
        color: colors.tertiary,
        paddingHorizontal: 4,
    },
    segmentText: {
        ...type.buttonSmall,
        color: colors.ink,
    },
    notice: {
        ...type.metaSmall,
        color: colors.muted,
        paddingHorizontal: 4,
        marginTop: 4,
    },
    errorBox: {
        marginTop: 4,
        gap: 10,
        alignItems: 'flex-start',
    },
    errorText: {
        ...type.metaSmall,
        color: colors.orange,
        paddingHorizontal: 4,
    },
    retry: {
        height: 36,
        paddingHorizontal: 14,
        borderRadius: radii.pill,
        borderWidth: 1,
        borderColor: colors.border,
        backgroundColor: colors.white,
        alignItems: 'center',
        justifyContent: 'center',
    },
    retryText: {
        ...type.buttonSmall,
        color: colors.ink,
    },
    actions: {
        marginTop: 'auto',
        paddingTop: 36,
        gap: 10,
    },
    primary: {
        height: 52,
        borderRadius: radii.card,
        backgroundColor: colors.orange,
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
        color: colors.white,
    },
    secondary: {
        height: 52,
        borderRadius: radii.card,
        borderWidth: 1,
        borderColor: colors.border,
        backgroundColor: colors.white,
        alignItems: 'center',
        justifyContent: 'center',
    },
    secondaryText: {
        ...type.button,
        color: colors.ink,
    },
    link: {
        height: 44,
        borderRadius: radii.card,
        alignItems: 'center',
        justifyContent: 'center',
    },
    linkText: {
        ...type.buttonSmall,
        color: colors.secondary,
    },
})
