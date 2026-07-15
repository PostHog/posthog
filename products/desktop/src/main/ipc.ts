/**
 * IPC surface for the shell UI. Sign-in verifies the personal API key against
 * the chosen cloud region from the main process (the key never round-trips
 * through the renderer once stored).
 */

import { ipcMain, shell } from 'electron'

import { IPC_CHANNELS, type SignInPayload, type SignInResult } from '../shared/ipc.ts'
import { resolveApiHost } from './regions.ts'
import type { AppState } from './state.ts'
import { isAllowedExternalUrl } from './window.ts'

export interface IpcActions {
    showShell: () => void
    showApp: () => void
}

async function verifyApiKey(apiHost: string, apiKey: string): Promise<SignInResult> {
    let response: Response
    try {
        response = await fetch(`${apiHost}/api/users/@me/`, {
            headers: { authorization: `Bearer ${apiKey}` },
            signal: AbortSignal.timeout(15000),
        })
    } catch {
        return { ok: false, error: `Could not reach ${apiHost}. Check your internet connection.` }
    }
    if (response.status === 401 || response.status === 403) {
        return { ok: false, error: 'That API key was rejected. Check the key and its scopes, then try again.' }
    }
    if (!response.ok) {
        return { ok: false, error: `Unexpected response from ${apiHost} (HTTP ${response.status}).` }
    }
    try {
        const user = (await response.json()) as { email?: string }
        return { ok: true, email: user.email || 'unknown' }
    } catch {
        return { ok: false, error: `Unexpected response from ${apiHost}. Is this a PostHog instance?` }
    }
}

export function registerIpcHandlers(state: AppState, actions: IpcActions): void {
    ipcMain.handle(IPC_CHANNELS.getState, () => state.snapshot())

    ipcMain.handle(IPC_CHANNELS.signIn, async (_event, payload: SignInPayload): Promise<SignInResult> => {
        if (!payload || typeof payload.apiKey !== 'string' || !payload.apiKey.trim()) {
            return { ok: false, error: 'Enter a personal API key.' }
        }
        const region = payload.region === 'eu' || payload.region === 'custom' ? payload.region : 'us'
        const customHost = typeof payload.customHost === 'string' ? payload.customHost.trim() : ''
        const apiHost = resolveApiHost(region, customHost)
        if (!apiHost) {
            return { ok: false, error: 'Enter a valid host URL, like https://posthog.example.com.' }
        }
        const result = await verifyApiKey(apiHost, payload.apiKey.trim())
        if (result.ok) {
            state.signIn(region, customHost, payload.apiKey.trim(), result.email)
        }
        return result
    })

    ipcMain.handle(IPC_CHANNELS.signOut, () => {
        state.signOut()
        actions.showShell()
    })

    ipcMain.handle(IPC_CHANNELS.openApp, () => {
        if (state.getAuth()) {
            actions.showApp()
        }
    })

    ipcMain.handle(IPC_CHANNELS.openExternal, (_event, url: unknown) => {
        if (typeof url === 'string' && isAllowedExternalUrl(url)) {
            void shell.openExternal(url)
        }
    })

    ipcMain.handle(IPC_CHANNELS.updateSettings, (_event, update: unknown) => {
        if (update && typeof update === 'object') {
            state.updateSettings(update)
        }
        return state.snapshot()
    })
}
