import { useRouter } from 'expo-router'

import { useAuthStore } from '@/auth/authStore'
import { useDemoMode } from '@/demo/demoMode'
import { type AsyncAction, useAsyncAction } from '@/lib/useAsyncAction'

/** For a demo session without an account, which has nothing to sign out of. */
export function useExitDemo(): () => void {
    const router = useRouter()
    const setDemo = useDemoMode((state) => state.setEnabled)
    return () => {
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
        setDemo(false)
        router.replace('/sign-in')
    })
}
