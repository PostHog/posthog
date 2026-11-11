import { QueryClientProvider } from '@tanstack/react-query'
import { DarkTheme, DefaultTheme, Stack, ThemeProvider, useSegments } from 'expo-router'
import * as SplashScreen from 'expo-splash-screen'
import { StatusBar } from 'expo-status-bar'
import { type ReactElement, useEffect, useMemo, useState } from 'react'
import { StyleSheet, View } from 'react-native'
import { GestureHandlerRootView } from 'react-native-gesture-handler'
import { KeyboardProvider } from 'react-native-keyboard-controller'
import { ReservedRegionsProvider } from 'react-native-reserved-regions'
import { SafeAreaProvider } from 'react-native-safe-area-context'
import { queryClient } from '@/api/queryClient'
import { installAuthProvider, useAuthStore } from '@/auth/authStore'
import { BootSplash } from '@/auth/BootSplash'
import { SPLASH_TIMEOUT_MS, shouldHideSplash, useBootGate } from '@/auth/bootGate'
import { useAuthRedirect } from '@/auth/useAuthRedirect'
import { useDemoHydrated, useDemoMode } from '@/demo/demoMode'
import '@/features/chat/draftPersistence'
import { AiApprovalDialog } from '@/features/ai/AiApprovalDialog'
import { useHedgehogWidgetSync } from '@/features/hedgehog/useHedgehogWidgetSync'
import { configureNotifications } from '@/features/notifications/pushRegistration'
import { useNotificationRouting } from '@/features/notifications/useNotificationRouting'
import { usePushRegistration } from '@/features/notifications/usePushRegistration'
import { installOfflineCache } from '@/features/offlineCache'
import { useAutomaticUpdates } from '@/features/updates/useAutomaticUpdates'
import { useChartWidgetSync } from '@/features/widgets/useChartWidgetSync'
import { track } from '@/lib/analytics'
import { initAnalytics } from '@/lib/posthogClient'
import { useScreenTracking } from '@/lib/useScreenTracking'
import { useAppearanceHydrated } from '@/ui/appearanceStore'
import { MobileScene } from '@/ui/MobileScene'
import { RouteErrorBoundary } from '@/ui/RouteErrorBoundary'
import { SceneFrame } from '@/ui/SceneFrame'
import { createStyles, useTheme } from '@/ui/theme'

export { RouteErrorBoundary as ErrorBoundary }

function renderMobileScene({ children, route }: { children: ReactElement; route: { name: string } }): ReactElement {
    return route.name === '(tabs)' ? children : <MobileScene>{children}</MobileScene>
}

SplashScreen.preventAutoHideAsync().catch(() => undefined)
SplashScreen.setOptions({ fade: true, duration: 250 })
installAuthProvider()
installOfflineCache()
configureNotifications()
initAnalytics()
const bootStartedAt = Date.now()

function hideNativeSplash(): void {
    SplashScreen.hideAsync().catch(() => undefined)
}

export default function RootLayout(): ReactElement {
    const demoHydrated = useDemoHydrated()
    const demoEnabled = useDemoMode((state) => state.enabled)
    const appearanceHydrated = useAppearanceHydrated()
    const authStatus = useAuthStore((state) => state.status)
    // Screens wait for the saved appearance too, so a Light or Dark override never paints a frame in the device scheme.
    const ready = demoHydrated && appearanceHydrated && authStatus !== 'loading'
    const firstScreenReady = useBootGate((state) => state.firstScreenReady)
    const segments = useSegments()
    const { colors, scheme } = useTheme()
    const navigationTheme = useMemo(() => {
        const base = scheme === 'dark' ? DarkTheme : DefaultTheme
        return {
            ...base,
            colors: {
                ...base.colors,
                primary: colors.ink,
                background: colors.background,
                card: colors.background,
                text: colors.ink,
                border: colors.hairline,
                notification: colors.orange,
            },
        }
    }, [colors, scheme])
    const styles = useStyles()
    const [timedOut, setTimedOut] = useState(false)
    const [splashHidden, setSplashHidden] = useState(false)

    useEffect(() => {
        void useAuthStore.getState().restore()
    }, [])

    useEffect(() => {
        if (!ready) {
            return
        }
        const timer = setTimeout(() => setTimedOut(true), SPLASH_TIMEOUT_MS)
        return () => clearTimeout(timer)
    }, [ready])

    useEffect(() => {
        if (splashHidden) {
            return
        }
        if (shouldHideSplash({ sessionReady: ready, firstScreenReady, segments, timedOut })) {
            setSplashHidden(true)
            hideNativeSplash()
            track('mobile_splash_hidden', {
                reason: firstScreenReady ? 'first_screen' : timedOut ? 'timeout' : 'not_held',
                wait_ms: Date.now() - bootStartedAt,
            })
        }
    }, [ready, firstScreenReady, segments, timedOut, splashHidden])

    useAuthRedirect()
    useScreenTracking(ready)
    usePushRegistration()
    useHedgehogWidgetSync()
    useChartWidgetSync()
    useNotificationRouting()
    useAutomaticUpdates(ready && segments[0] === '(tabs)')

    return (
        <GestureHandlerRootView
            style={styles.root}
            collapsable={false}
            importantForAccessibility="no"
            accessibilityLabel={
                demoHydrated && demoEnabled && authStatus === 'signed_out' ? undefined : 'ph-no-capture'
            }
        >
            <SafeAreaProvider>
                <ReservedRegionsProvider style={styles.root}>
                    <SceneFrame>
                        <KeyboardProvider>
                            <QueryClientProvider client={queryClient}>
                                <StatusBar style={scheme === 'dark' ? 'light' : 'dark'} />
                                {/* Screens mount only after the session loads, so no query runs without a token. */}
                                {ready ? (
                                    <ThemeProvider value={navigationTheme}>
                                        <Stack
                                            screenLayout={renderMobileScene}
                                            screenOptions={{
                                                headerShown: false,
                                                contentStyle: { backgroundColor: colors.background },
                                            }}
                                        >
                                            <Stack.Screen
                                                name="chat"
                                                dangerouslySingular={(): string => 'chat'}
                                                options={{
                                                    presentation: 'card',
                                                }}
                                            />
                                        </Stack>
                                    </ThemeProvider>
                                ) : null}
                                {!splashHidden && (
                                    <View style={StyleSheet.absoluteFill} onLayout={hideNativeSplash}>
                                        <BootSplash />
                                    </View>
                                )}
                                <AiApprovalDialog />
                            </QueryClientProvider>
                        </KeyboardProvider>
                    </SceneFrame>
                </ReservedRegionsProvider>
            </SafeAreaProvider>
        </GestureHandlerRootView>
    )
}

const useStyles = createStyles(({ colors }) => ({
    root: {
        flex: 1,
        backgroundColor: colors.background,
    },
}))
