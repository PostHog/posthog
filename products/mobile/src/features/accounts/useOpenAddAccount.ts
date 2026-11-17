import { useRouter } from 'expo-router'
import { useCallback } from 'react'

import { type StoredAccount, useAuthStore } from '@/auth/authStore'
import { track } from '@/lib/analytics'

export type AddAccountSource = 'project_card' | 'settings'

/**
 * Opens the sign-in screen in add mode. `reauth` is an account that needs a new sign-in: the form starts on its host,
 * and a sign-in to the same login gives it its session back.
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
