import { useRouter } from 'expo-router'

import { useAuthStore } from '@/auth/authStore'
import { useDemoMode } from '@/demo/demoMode'
import { track } from '@/lib/analytics'
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
export function useSignOutAction(): AsyncAction<[]> {
    const router = useRouter()
    const signOut = useAuthStore((state) => state.signOut)
    const setDemo = useDemoMode((state) => state.setEnabled)
    return useAsyncAction(async () => {
        await signOut()
        if (useDemoMode.getState().enabled) {
            track('mobile_demo_ended', { from: 'sign_out' })
        }
        setDemo(false)
        router.replace('/sign-in')
    })
}
