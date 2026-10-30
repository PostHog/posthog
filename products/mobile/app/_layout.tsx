import { QueryClientProvider } from '@tanstack/react-query'
import { Stack, useSegments } from 'expo-router'
import * as SplashScreen from 'expo-splash-screen'
import { StatusBar } from 'expo-status-bar'
import { type ReactElement, useEffect, useState } from 'react'
import { StyleSheet, View } from 'react-native'
import { GestureHandlerRootView } from 'react-native-gesture-handler'
import { KeyboardProvider } from 'react-native-keyboard-controller'
import { SafeAreaProvider } from 'react-native-safe-area-context'

import { queryClient } from '@/api/queryClient'
import { installAuthProvider, useAuthStore } from '@/auth/authStore'
import { BootSplash } from '@/auth/BootSplash'
import { SPLASH_TIMEOUT_MS, shouldHideSplash, useBootGate } from '@/auth/bootGate'
import { useAuthRedirect } from '@/auth/useAuthRedirect'
import { useDemoHydrated } from '@/demo/demoMode'
import '@/features/chat/draftPersistence'
import { AiApprovalDialog } from '@/features/ai/AiApprovalDialog'
import { useHedgehogWidgetSync } from '@/features/hedgehog/useHedgehogWidgetSync'
import { configureNotifications } from '@/features/notifications/pushRegistration'
import { useNotificationRouting } from '@/features/notifications/useNotificationRouting'
import { usePushRegistration } from '@/features/notifications/usePushRegistration'
import { useAutomaticUpdates } from '@/features/updates/useAutomaticUpdates'
import { track } from '@/lib/analytics'
import { initAnalytics } from '@/lib/posthogClient'
import { useScreenTracking } from '@/lib/useScreenTracking'
import { useAppearanceHydrated } from '@/ui/appearanceStore'
import { RouteErrorBoundary } from '@/ui/RouteErrorBoundary'
import { createStyles, useTheme } from '@/ui/theme'

export { RouteErrorBoundary as ErrorBoundary }

SplashScreen.preventAutoHideAsync().catch(() => undefined)
SplashScreen.setOptions({ fade: true, duration: 250 })
installAuthProvider()
configureNotifications()
initAnalytics()
const bootStartedAt = Date.now()

function hideNativeSplash(): void {
    SplashScreen.hideAsync().catch(() => undefined)
}

export default function RootLayout(): ReactElement {
    const demoHydrated = useDemoHydrated()
    const appearanceHydrated = useAppearanceHydrated()
    const authStatus = useAuthStore((state) => state.status)
    // Screens wait for the saved appearance too, so a Light or Dark override never paints a frame in the device scheme.
    const ready = demoHydrated && appearanceHydrated && authStatus !== 'loading'
    const firstScreenReady = useBootGate((state) => state.firstScreenReady)
    const segments = useSegments()
    const { colors, scheme } = useTheme()
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
    useNotificationRouting()
    useAutomaticUpdates(ready && segments[0] === '(tabs)')

    return (
        <GestureHandlerRootView style={styles.root}>
            <SafeAreaProvider>
                <KeyboardProvider>
                    <QueryClientProvider client={queryClient}>
                        <StatusBar style={scheme === 'dark' ? 'light' : 'dark'} />
                        {/* Screens mount only after the session loads, so no query runs without a token. */}
                        {ready ? (
                            <Stack
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
                        ) : null}
                        {!splashHidden && (
                            <View style={StyleSheet.absoluteFill} onLayout={hideNativeSplash}>
                                <BootSplash />
                            </View>
                        )}
                        <AiApprovalDialog />
                    </QueryClientProvider>
                </KeyboardProvider>
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
