import { useRouter } from 'expo-router'
import { useState } from 'react'

import { useAuthStore } from '@/auth/authStore'
import { useDemoMode } from '@/demo/demoMode'
import { track } from '@/lib/analytics'
import { toError } from '@/lib/errors'
import { type AsyncAction, useAsyncAction } from '@/lib/useAsyncAction'

/** For a demo session without an account, which has nothing to sign out of. */
export function useExitDemo(): () => void {
    const router = useRouter()
    const setDemo = useDemoMode((state) => state.setEnabled)
    return () => {
        track('mobile_demo_ended', { from: 'sign_out' })
        setDemo(false)
        router.replace('/sign-in')
    }
}

// Demo mode stays on until the session ends, so no screen loads live data in between.
export function useSignOutAction(): AsyncAction<[]> & { error: string | null; clearError: () => void } {
    const router = useRouter()
    const [error, setError] = useState<string | null>(null)
    const signOut = useAuthStore((state) => state.signOut)
    const setDemo = useDemoMode((state) => state.setEnabled)
    const action = useAsyncAction(async () => {
        setError(null)
        try {
            await signOut()
            if (useDemoMode.getState().enabled) {
                track('mobile_demo_ended', { from: 'sign_out' })
            }
            setDemo(false)
            router.replace('/sign-in')
        } catch (caught) {
            setError(toError(caught).message)
        }
    })
    return { ...action, error, clearError: () => setError(null) }
}
