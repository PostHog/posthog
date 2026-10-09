import { QueryClientProvider } from '@tanstack/react-query'
import { Stack } from 'expo-router'
import * as SplashScreen from 'expo-splash-screen'
import { StatusBar } from 'expo-status-bar'
import { type ReactElement, useEffect } from 'react'
import { StyleSheet } from 'react-native'
import { GestureHandlerRootView } from 'react-native-gesture-handler'
import { KeyboardProvider } from 'react-native-keyboard-controller'
import { SafeAreaProvider } from 'react-native-safe-area-context'

import { queryClient } from '@/api/queryClient'
import { installAuthProvider, useAuthStore } from '@/auth/authStore'
import { BootSplash } from '@/auth/BootSplash'
import { useAuthRedirect } from '@/auth/useAuthRedirect'
import { useDemoHydrated } from '@/demo/demoMode'
import { configureNotifications } from '@/features/notifications/pushRegistration'
import { useNotificationRouting } from '@/features/notifications/useNotificationRouting'
import { usePushRegistration } from '@/features/notifications/usePushRegistration'
import { initAnalytics } from '@/lib/posthogClient'
import { RouteErrorBoundary } from '@/ui/RouteErrorBoundary'
import { colors } from '@/ui/tokens'

export { RouteErrorBoundary as ErrorBoundary }

SplashScreen.preventAutoHideAsync().catch(() => undefined)
installAuthProvider()
configureNotifications()
initAnalytics()

export default function RootLayout(): ReactElement {
    const demoHydrated = useDemoHydrated()
    const authStatus = useAuthStore((state) => state.status)
    const ready = demoHydrated && authStatus !== 'loading'

    useEffect(() => {
        void useAuthStore.getState().restore()
    }, [])

    useEffect(() => {
        if (ready) {
            SplashScreen.hideAsync().catch(() => undefined)
        }
    }, [ready])

    useAuthRedirect()
    usePushRegistration()
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
