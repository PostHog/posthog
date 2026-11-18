import { useRouter } from 'expo-router'
import { useCallback } from 'react'

import { type StoredAccount, useAuthStore } from '@/auth/authStore'
import { track } from '@/lib/analytics'

/** `feature_reauth`: a feature's Sign in again, for a scope that the active account's grant lacks. */
export type AddAccountSource = 'project_card' | 'settings' | 'feature_reauth'

/**
 * Opens the sign-in screen in add mode. `reauth` is an account to sign in again: the form starts on its host, and a
 * sign-in to the same login replaces its session.
 */
export function useOpenAddAccount(): (from: AddAccountSource, reauth?: StoredAccount) => void {
    const router = useRouter()
    return useCallback(
        (from, reauth) => {
            track('mobile_account_add_started', {
                from,
                reauth: reauth !== undefined,
                account_count: useAuthStore.getState().accounts.length,
            })
            router.push({
                pathname: '/sign-in',
                params: reauth ? { mode: 'add', reauth: reauth.key } : { mode: 'add' },
            })
        },
        [router]
    )
}
