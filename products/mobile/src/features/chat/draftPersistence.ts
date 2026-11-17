import { accountKey as accountDigest } from '@/auth/accountKey'
import { addAccountRemovedTask, addSessionEndTask, useAuthStore } from '@/auth/authStore'
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

async function draftAccountKey(host: string, userUuid: string): Promise<string> {
    return `mobile-drafts-${await accountDigest(host, userUuid)}`
}

async function accountKey(): Promise<string | null> {
    const state = useAuthStore.getState()
    return state.host && state.user ? draftAccountKey(state.host, state.user.uuid) : null
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

// Outstanding sends belong to the session that left, so they must not write a draft back.
addSessionEndTask(async () => {
    await chatDrafts.clear([])
})

addAccountRemovedTask(async ({ host, userUuid }) => {
    const account = await draftAccountKey(host, userUuid)
    await registryQueue
    const scopes = await readScopes(account)
    await chatDrafts.remove(scopes)
    await storage.removeItem(`${account}.scopes`)
})
