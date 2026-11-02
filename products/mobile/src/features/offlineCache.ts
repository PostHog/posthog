import * as Crypto from 'expo-crypto'
import { AppState } from 'react-native'
import { queryClient } from '@/api/queryClient'
import { persistReadCache } from '@/api/readCache'
import { ReadCacheStore } from '@/api/readCacheStore'
import { missingViewsScope } from '@/api/scopeErrors'
import { addSessionEndTask, useAuthStore } from '@/auth/authStore'
import { getSessionIdentity, getSessionTokens } from '@/auth/tokens'
import { useScopeErrorStore } from '@/features/views/useViewsAccess'
import { useItemErrors } from '@/features/views/viewsCache'
import { secureStorage } from '@/lib/secureStorage'

const store = new ReadCacheStore(secureStorage)

function identity(): string | null {
    const state = useAuthStore.getState()
    const owner = getSessionIdentity()
    return getSessionTokens() &&
        state.signedIn &&
        state.host &&
        state.user &&
        state.projectId !== null &&
        owner?.host === state.host &&
        owner.userUuid === state.user.uuid
        ? JSON.stringify([state.host, state.user.uuid, state.projectId])
        : null
}

async function accountKey(host: string, userId: string): Promise<string> {
    const hash = await Crypto.digestStringAsync(Crypto.CryptoDigestAlgorithm.SHA256, JSON.stringify([host, userId]))
    return `mobile-read-cache-v1-${hash}`
}

export function installOfflineCache(): () => void {
    let active: ReturnType<typeof persistReadCache> | undefined
    let previous: string | null = null
    let generation = 0
    const update = (): void => {
        const target = identity()
        if (target === previous) return
        previous = target
        const mine = ++generation
        active?.stop()
        active = undefined
        if (!target) return
        const state = useAuthStore.getState()
        if (!state.host || !state.user || state.projectId === null) return
        const { host, projectId } = state
        void accountKey(host, state.user.uuid)
            .then((account) => {
                if (mine !== generation || identity() !== target) return
                active = persistReadCache(
                    queryClient,
                    store,
                    { account, host, projectId },
                    () => identity() === target,
                    (key) =>
                        key[0] === 'views' &&
                        (useScopeErrorStore.getState().reported.views !== null ||
                            (getSessionTokens()?.kind === 'oauth' &&
                                missingViewsScope(getSessionTokens()?.grantedScopes ?? null) !== null) ||
                            ['deleted', 'no_access', 'scope'].includes(
                                useItemErrors.getState().errors[JSON.stringify(key)] ?? ''
                            ))
                )
            })
            .catch(() => undefined)
    }
    const unsubscribe = useAuthStore.subscribe(update)
    const unsubscribeErrors = useItemErrors.subscribe(() => active?.purgeDeniedViews())
    const unsubscribeScopes = useScopeErrorStore.subscribe(() => active?.purgeDeniedViews())
    const unsubscribeEnd = addSessionEndTask(async () => {
        generation++
        previous = null
        active?.stop()
        active = undefined
        const state = useAuthStore.getState()
        if (state.host && state.user) await store.clearAccount(await accountKey(state.host, state.user.uuid))
    })
    const appState = AppState.addEventListener('change', (state) => {
        if (state !== 'active') void active?.flush()
    })
    update()
    return () => {
        generation++
        active?.stop()
        unsubscribe()
        unsubscribeErrors()
        unsubscribeScopes()
        unsubscribeEnd()
        appState.remove()
    }
}
