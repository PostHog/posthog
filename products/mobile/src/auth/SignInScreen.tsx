import { useLocalSearchParams, useRouter } from 'expo-router'
import { type ReactElement, useState } from 'react'

import { sessionEndedAccount } from '@/features/accounts/accountLabel'
import { currentDefaultPageHref } from '@/features/settings/defaultPageStore'
import { track } from '@/lib/analytics'

import { useAuthStore } from './authStore'
import { SessionEndedView } from './SessionEndedView'
import { SignInForm } from './SignInForm'

function firstParam(value: string | string[] | undefined): string | undefined {
    return Array.isArray(value) ? value[0] : value
}

/**
 * `/sign-in`. Signed out it is the sign-in form, or the session-ended screen after an expiry. `mode=add` adds an
 * account while one is signed in, and `reauth=<account key>` signs a stored account in again.
 */
export function SignInScreen(): ReactElement {
    const router = useRouter()
    const params = useLocalSearchParams<{ mode?: string; reauth?: string }>()
    const status = useAuthStore((state) => state.status)
    const accounts = useAuthStore((state) => state.accounts)
    const signedOutReason = useAuthStore((state) => state.signedOutReason)
    // Sign in again on the session-ended screen opens the form here, so Cancel can return to that screen.
    const [localReauth, setLocalReauth] = useState<string | null>(null)
    const addParam = firstParam(params.mode) === 'add'
    const reauthKey = localReauth ?? (addParam ? firstParam(params.reauth) : undefined)
    const reauth = reauthKey ? (accounts.find((account) => account.key === reauthKey) ?? null) : null
    const adding = reauth !== null || (addParam && status === 'signed_in')
    const ended = adding ? null : sessionEndedAccount({ accounts, signedOutReason, status })

    if (ended) {
        return <SessionEndedView account={ended} onSignInAgain={() => setLocalReauth(ended.key)} />
    }

    const cancel = (): void => {
        track('mobile_account_add_cancelled', { reauth: reauth !== null, account_count: accounts.length })
        if (localReauth) {
            setLocalReauth(null)
        } else if (router.canGoBack()) {
            router.back()
        } else {
            router.replace(currentDefaultPageHref())
        }
    }

    return (
        <SignInForm
            key={reauth?.key ?? (adding ? 'add' : 'sign_in')}
            mode={adding ? 'add' : 'sign_in'}
            reauth={reauth}
            onCancel={adding ? cancel : null}
        />
    )
}
