import type { QueryKey } from '@tanstack/react-query'
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

function viewsScopeDenied(): boolean {
    const tokens = getSessionTokens()
    return (
        useScopeErrorStore.getState().reported.views !== null ||
        (tokens?.kind === 'oauth' && missingViewsScope(tokens.grantedScopes) !== null)
    )
}

export function installOfflineCache(): () => void {
    let active: ReturnType<typeof persistReadCache> | undefined
    const sessions = new Map<string, ReturnType<typeof persistReadCache>>()
    let owner: string | null = null
    let previous: string | null = null
    let generation = 0
    const update = (): void => {
        const target = identity()
        if (target === previous) return
        previous = target
        const mine = ++generation
        active?.pause()
        active = undefined
        const nextOwner = target ? JSON.stringify(JSON.parse(target).slice(0, 2)) : null
        if (owner !== nextOwner) {
            for (const session of sessions.values()) session.stop()
            sessions.clear()
            owner = nextOwner
        }
        if (!target) return
        const state = useAuthStore.getState()
        if (!state.host || !state.user || state.projectId === null) return
        const { host, projectId } = state
        void accountKey(host, state.user.uuid)
            .then(async (account) => {
                if (mine !== generation || identity() !== target) return
                if (viewsScopeDenied()) await store.evictAccountViews(account, host)
                if (mine !== generation || identity() !== target) return
                active = persistReadCache(
                    queryClient,
                    store,
                    { account, host, projectId },
                    () => identity() === target,
                    (key) =>
                        key[0] === 'views' &&
                        (viewsScopeDenied() ||
                            ['deleted', 'no_access', 'scope'].includes(
                                useItemErrors.getState().errors[JSON.stringify(key)] ?? ''
                            )),
                    () => {
                        const verified = identity()
                        return verified !== null && JSON.stringify(JSON.parse(verified).slice(0, 2)) === nextOwner
                    }
                )
                sessions.get(target)?.stop()
                sessions.set(target, active)
            })
            .catch(() => undefined)
    }
    const unsubscribe = useAuthStore.subscribe(update)
    const purge = (): void => {
        const keys: QueryKey[] = []
        for (const key of Object.keys(useItemErrors.getState().errors)) {
            try {
                const parsed: unknown = JSON.parse(key)
                if (Array.isArray(parsed)) keys.push(parsed)
            } catch {}
        }
        for (const session of sessions.values()) session.purgeDeniedViews(keys)
        const target = identity()
        if (!target || !viewsScopeDenied()) return
        const [host, userId] = JSON.parse(target) as [string, string, number]
        void accountKey(host, userId)
            .then(async (account) => {
                const verified = identity()
                if (!verified || JSON.stringify(JSON.parse(verified).slice(0, 2)) !== JSON.stringify([host, userId]))
                    return
                await store.evictAccountViews(account, host)
            })
            .catch(() => undefined)
    }
    const unsubscribeErrors = useItemErrors.subscribe(purge)
    const unsubscribeScopes = useScopeErrorStore.subscribe(purge)
    const unsubscribeEnd = addSessionEndTask(async () => {
        generation++
        previous = null
        for (const session of sessions.values()) session.stop()
        sessions.clear()
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
        for (const session of sessions.values()) session.stop()
        sessions.clear()
        unsubscribe()
        unsubscribeErrors()
        unsubscribeScopes()
        unsubscribeEnd()
        appState.remove()
    }
}
