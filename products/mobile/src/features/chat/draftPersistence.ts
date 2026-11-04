import * as Crypto from 'expo-crypto'

import { addSessionEndTask, useAuthStore } from '@/auth/authStore'
import { getSessionTokens } from '@/auth/tokens'

import { secureStorage as storage } from '@/lib/secureStorage'

import { DraftStore } from './draftStore'

export const chatDrafts = new DraftStore(storage)

export function draftIdentity(): string | null {
    const state = useAuthStore.getState()
    return getSessionTokens() && state.signedIn && state.host && state.user && state.projectId !== null
        ? JSON.stringify([state.host.replace(/\/$/, ''), state.user.uuid, state.projectId])
        : null
}

async function accountKey(): Promise<string | null> {
    const state = useAuthStore.getState()
    if (!state.host || !state.user) {
        return null
    }
    const hash = await Crypto.digestStringAsync(
        Crypto.CryptoDigestAlgorithm.SHA256,
        JSON.stringify([state.host.replace(/\/$/, ''), state.user.uuid])
    )
    return `mobile-drafts-${hash}`
}

async function readScopes(account: string): Promise<string[]> {
    try {
        const raw: unknown = JSON.parse((await storage.getItem(`${account}.scopes`)) ?? '[]')
        return Array.isArray(raw)
            ? raw.filter(
                  (value): value is string =>
                      typeof value === 'string' && value.startsWith(`${account}.`) && value !== `${account}.scopes`
              )
            : []
    } catch {
        return []
    }
}

let registryQueue: Promise<unknown> = Promise.resolve()

export async function draftScope(identity: string): Promise<string | null> {
    const account = await accountKey()
    if (!account || draftIdentity() !== identity) {
        return null
    }
    const scope = `${account}.${useAuthStore.getState().projectId}`
    const register = registryQueue.then(async () => {
        if (draftIdentity() !== identity) {
            return
        }
        const scopes = await readScopes(account)
        if (!scopes.includes(scope)) {
            await storage.setItem(`${account}.scopes`, JSON.stringify([...scopes, scope]))
        }
    })
    registryQueue = register.catch(() => undefined)
    await register
    return draftIdentity() === identity ? scope : null
}

addSessionEndTask(async () => {
    // Invalidate outstanding sends before awaiting storage, while auth still identifies the departing account.
    await chatDrafts.clear([])
    const account = await accountKey()
    await registryQueue
    if (account) {
        const scopes = await readScopes(account)
        await chatDrafts.clear(scopes)
        await storage.removeItem(`${account}.scopes`)
    }
})
