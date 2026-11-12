import { useGlobalSearchParams, usePathname, useRootNavigationState, useRouter, useSegments } from 'expo-router'
import { useEffect } from 'react'

import { useDemoMode } from '@/demo/demoMode'

import { useAuthStore } from './authStore'
import { signInReturnHref } from './signInReturn'

// Covers a refresh token the server rejects in the middle of a session, not only the explicit sign-out buttons.
export function useAuthRedirect(): void {
    const router = useRouter()
    const segments = useSegments()
    const pathname = usePathname()
    const params = useGlobalSearchParams()
    const navigationReady = Boolean(useRootNavigationState()?.key)
    const status = useAuthStore((state) => state.status)
    const demo = useDemoMode((state) => state.enabled)
    const onSignIn = segments[0] === 'sign-in'
    const redirect = navigationReady && status === 'signed_out' && !demo && !onSignIn

    // biome-ignore lint/correctness/useExhaustiveDependencies: the screen is read only at the moment of the redirect.
    useEffect(() => {
        if (redirect) {
            const next = signInReturnHref(pathname, segments, params)
            router.replace(next ? { pathname: '/sign-in', params: { next } } : '/sign-in')
        }
    }, [redirect, router])
}
