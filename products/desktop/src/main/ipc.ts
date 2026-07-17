/**
 * IPC surface for the shell UI. Sign-in happens in the main process either by
 * verifying a pasted personal API key or by running the OAuth browser flow;
 * credentials never round-trip through the renderer once stored.
 */

import { app, BrowserWindow, ipcMain, shell } from 'electron'

import { type BrowserSignInPayload, IPC_CHANNELS, type SignInPayload, type SignInResult } from '../shared/ipc.ts'
import { type OAuthBrowserFlow, oauthClientIdFor } from './oauth.ts'
import { resolveApiHost } from './regions.ts'
import type { AppState } from './state.ts'
import { isAllowedExternalUrl } from './window.ts'

export interface IpcActions {
    showShell: () => void
    showApp: () => void
}

async function verifyBearerToken(apiHost: string, token: string, rejectedError: string): Promise<SignInResult> {
    let response: Response
    try {
        response = await fetch(`${apiHost}/api/users/@me/`, {
            headers: { authorization: `Bearer ${token}` },
            signal: AbortSignal.timeout(15000),
        })
    } catch {
        return { ok: false, error: `Could not reach ${apiHost}. Check your internet connection.` }
    }
    if (response.status === 401 || response.status === 403) {
        return { ok: false, error: rejectedError }
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

function resolveRegion(payload: { region?: unknown; customHost?: unknown }): {
    region: 'us' | 'eu' | 'custom'
    customHost: string
    apiHost: string | null
} {
    const region = payload.region === 'eu' || payload.region === 'custom' ? payload.region : 'us'
    const customHost = typeof payload.customHost === 'string' ? payload.customHost.trim() : ''
    return { region, customHost, apiHost: resolveApiHost(region, customHost) }
}

function focusMainWindow(): void {
    const win = BrowserWindow.getAllWindows()[0]
    if (win) {
        if (win.isMinimized()) {
            win.restore()
        }
        win.show()
    }
    app.focus({ steal: true })
}

export function registerIpcHandlers(state: AppState, oauthFlow: OAuthBrowserFlow, actions: IpcActions): void {
    ipcMain.handle(IPC_CHANNELS.getState, () => state.snapshot())

    ipcMain.handle(IPC_CHANNELS.signIn, async (_event, payload: SignInPayload): Promise<SignInResult> => {
        if (!payload || typeof payload.apiKey !== 'string' || !payload.apiKey.trim()) {
            return { ok: false, error: 'Enter a personal API key.' }
        }
        const { region, customHost, apiHost } = resolveRegion(payload)
        if (!apiHost) {
            return { ok: false, error: 'Enter a valid host URL, like https://posthog.example.com.' }
        }
        const result = await verifyBearerToken(
            apiHost,
            payload.apiKey.trim(),
            'That API key was rejected. Check the key and its scopes, then try again.'
        )
        if (result.ok) {
            state.signIn(region, customHost, payload.apiKey.trim(), result.email)
        }
        return result
    })

    ipcMain.handle(
        IPC_CHANNELS.signInWithBrowser,
        async (_event, payload: BrowserSignInPayload): Promise<SignInResult> => {
            const { region, customHost, apiHost } = resolveRegion(payload ?? {})
            if (!apiHost) {
                return { ok: false, error: 'Enter a valid host URL, like https://posthog.example.com.' }
            }
            const clientId = oauthClientIdFor(region)
            if (!clientId) {
                return { ok: false, error: 'Browser sign-in is not available for this host. Use a personal API key.' }
            }
            const appOrigin = state.snapshot().appOrigin
            if (!appOrigin) {
                return { ok: false, error: 'The local server is not running yet. Try again in a moment.' }
            }
            // `localhost` (not 127.0.0.1) and path `/callback` so the port-stripped
            // URI matches the registered http://localhost/callback under RFC 8252
            // port flexibility
            const redirectUri = `http://localhost:${new URL(appOrigin).port}/callback`
            const { url, completion } = oauthFlow.begin({ apiHost, clientId, redirectUri })
            void shell.openExternal(url)
            const result = await completion
            if (!result.ok) {
                return result
            }
            const verified = await verifyBearerToken(
                apiHost,
                result.tokens.accessToken,
                'PostHog rejected the new session. Try signing in again.'
            )
            if (!verified.ok) {
                return verified
            }
            state.signInOAuth(region, customHost, result.tokens, clientId, verified.email)
            focusMainWindow()
            return verified
        }
    )

    ipcMain.handle(IPC_CHANNELS.signOut, () => {
        oauthFlow.cancel('Signed out.')
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
