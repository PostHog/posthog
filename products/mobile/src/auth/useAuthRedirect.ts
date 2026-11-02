import { useRootNavigationState, useRouter, useSegments } from 'expo-router'
import { useEffect } from 'react'

import { useDemoMode } from '@/demo/demoMode'

import { useAuthStore } from './authStore'

// Covers a refresh token the server rejects in the middle of a session, not only the explicit sign-out buttons.
export function useAuthRedirect(): void {
    const router = useRouter()
    const segments = useSegments()
    const navigationReady = Boolean(useRootNavigationState()?.key)
    const status = useAuthStore((state) => state.status)
    const demo = useDemoMode((state) => state.enabled)
    const onSignIn = segments[0] === 'sign-in'

    useEffect(() => {
        if (navigationReady && status === 'signed_out' && !demo && !onSignIn) {
            router.replace('/sign-in')
        }
    }, [navigationReady, status, demo, onSignIn, router])
}
