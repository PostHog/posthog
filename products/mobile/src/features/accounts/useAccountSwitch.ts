import { useCallback, useRef, useState } from 'react'

import { AccountNeedsSignInError, type AccountSwitchSource, useAuthStore } from '@/auth/authStore'
import { track } from '@/lib/analytics'

import { postAccountNotice } from './accountNotices'

export interface AccountSwitchTarget {
    key: string
    projectId?: number
}

export interface AccountSwitch {
    /** The switch in flight. Every other switch control stays disabled until it settles. */
    pending: AccountSwitchTarget | null
    /** The last switch that failed for a reason a retry can fix. */
    failed: AccountSwitchTarget | null
    run: (target: AccountSwitchTarget) => Promise<void>
}

/**
 * Switches to another stored account. A refused session needs no message here: the store marks the account
 * `needsSignIn`, and every account list then offers Sign in again for it.
 */
export function useAccountSwitch(from: AccountSwitchSource): AccountSwitch {
    const [pending, setPending] = useState<AccountSwitchTarget | null>(null)
    const [failed, setFailed] = useState<AccountSwitchTarget | null>(null)
    const inFlight = useRef(false)
    const run = useCallback(
        async (target: AccountSwitchTarget): Promise<void> => {
            if (inFlight.current) {
                return
            }
            inFlight.current = true
            setPending(target)
            setFailed(null)
            try {
                await useAuthStore.getState().switchAccount(target.key, { projectId: target.projectId, from })
                const { activeAccountKey, status } = useAuthStore.getState()
                if (activeAccountKey === target.key && status === 'signed_in') {
                    postAccountNotice({ kind: 'switched' })
                }
            } catch (error) {
                const needsSignIn = error instanceof AccountNeedsSignInError
                track('mobile_account_switch_failed', { from, reason: needsSignIn ? 'needs_sign_in' : 'error' })
                if (!needsSignIn) {
                    setFailed(target)
                }
            } finally {
                inFlight.current = false
                setPending(null)
            }
        },
        [from]
    )
    return { pending, failed, run }
}
