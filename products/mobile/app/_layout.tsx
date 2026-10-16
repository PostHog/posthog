import { QueryClientProvider } from '@tanstack/react-query'
import { Stack, useSegments } from 'expo-router'
import * as SplashScreen from 'expo-splash-screen'
import { StatusBar } from 'expo-status-bar'
import { type ReactElement, useEffect, useRef, useState } from 'react'
import { StyleSheet } from 'react-native'
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
import { useHedgehogWidgetSync } from '@/features/hedgehog/useHedgehogWidgetSync'
import { configureNotifications } from '@/features/notifications/pushRegistration'
import { useNotificationRouting } from '@/features/notifications/useNotificationRouting'
import { usePushRegistration } from '@/features/notifications/usePushRegistration'
import { track } from '@/lib/analytics'
import { initAnalytics } from '@/lib/posthogClient'
import { useScreenTracking } from '@/lib/useScreenTracking'
import { RouteErrorBoundary } from '@/ui/RouteErrorBoundary'
import { colors } from '@/ui/tokens'

export { RouteErrorBoundary as ErrorBoundary }

SplashScreen.preventAutoHideAsync().catch(() => undefined)
SplashScreen.setOptions({ fade: true, duration: 250 })
installAuthProvider()
configureNotifications()
initAnalytics()
const bootStartedAt = Date.now()

export default function RootLayout(): ReactElement {
    const demoHydrated = useDemoHydrated()
    const authStatus = useAuthStore((state) => state.status)
    const ready = demoHydrated && authStatus !== 'loading'
    const firstScreenReady = useBootGate((state) => state.firstScreenReady)
    const segments = useSegments()
    const [timedOut, setTimedOut] = useState(false)
    const splashHidden = useRef(false)

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
        if (splashHidden.current) {
            return
        }
        if (shouldHideSplash({ sessionReady: ready, firstScreenReady, segments, timedOut })) {
            splashHidden.current = true
            SplashScreen.hideAsync().catch(() => undefined)
            track('mobile_splash_hidden', {
                reason: firstScreenReady ? 'first_screen' : timedOut ? 'timeout' : 'not_held',
                wait_ms: Date.now() - bootStartedAt,
            })
        }
    }, [ready, firstScreenReady, segments, timedOut])

    useAuthRedirect()
    useScreenTracking(ready)
    usePushRegistration()
    useHedgehogWidgetSync()
    useNotificationRouting()

    return (
        <GestureHandlerRootView style={styles.root}>
            <SafeAreaProvider>
                <KeyboardProvider>
                    <QueryClientProvider client={queryClient}>
                        {/* Dark status bar content on the light background; the app has no dark theme yet. */}
                        <StatusBar style="dark" />
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
                                    options={{
                                        presentation: 'transparentModal',
                                        animation: 'none',
                                        contentStyle: { backgroundColor: 'transparent' },
                                    }}
                                />
                            </Stack>
                        ) : (
                            <BootSplash />
                        )}
                    </QueryClientProvider>
                </KeyboardProvider>
            </SafeAreaProvider>
        </GestureHandlerRootView>
    )
}

const styles = StyleSheet.create({
    root: {
        flex: 1,
        backgroundColor: colors.background,
    },
})
