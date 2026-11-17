import { useRouter } from 'expo-router'
import { useState } from 'react'

import { useAuthStore } from '@/auth/authStore'
import { useDemoMode } from '@/demo/demoMode'
import { accountLabel } from '@/features/accounts/accountLabel'
import { postAccountNotice } from '@/features/accounts/accountNotices'
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

/**
 * Signs out of one account by key, or of every account. Demo mode stays on until the session ends, so no screen loads
 * live data in between.
 */
export function useSignOutAction(): AsyncAction<[target: string | 'all']> & {
    error: string | null
    clearError: () => void
} {
    const router = useRouter()
    const [error, setError] = useState<string | null>(null)
    const setDemo = useDemoMode((state) => state.setEnabled)
    const action = useAsyncAction(async (target: string | 'all') => {
        setError(null)
        const before = useAuthStore.getState()
        const leaving = before.accounts.find((account) => account.key === target)
        const left = leaving ? accountLabel(leaving, before.accounts) : null
        try {
            if (target === 'all') {
                await before.signOutAll()
            } else {
                await before.signOutAccount(target)
            }
            const after = useAuthStore.getState()
            const sessionEnded = after.status !== 'signed_in' || after.activeAccountKey !== before.activeAccountKey
            if (sessionEnded) {
                if (useDemoMode.getState().enabled) {
                    track('mobile_demo_ended', { from: 'sign_out' })
                }
                setDemo(false)
            }
            // Signing out of the active one of several accounts switches to another, and the root layout opens its
            // start page, where the toast names the account that the app switched to.
            if (after.status !== 'signed_in') {
                router.replace('/sign-in')
            } else if (left && after.activeAccountKey !== before.activeAccountKey) {
                postAccountNotice({ kind: 'signed_out', left })
            }
        } catch (caught) {
            setError(toError(caught).message)
        }
    })
    return { ...action, error, clearError: () => setError(null) }
}
