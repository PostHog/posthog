/**
 * Main-process entry point and composition root for the PostHog desktop app.
 *
 * Boot order matters: app identity (name + userData path) is set before any
 * other Electron API runs, so dev builds never share state with packaged ones
 * (pattern borrowed from posthog/code).
 */

import { app, BrowserWindow, dialog, shell } from 'electron'
import * as path from 'node:path'

import { registerIpcHandlers } from './ipc.ts'
import { buildAppMenu } from './menu.ts'
import { isFrontendBuilt, type LocalBackend, startLocalBackend } from './server/backend.ts'
import { type DesktopSettings, DEFAULT_SETTINGS, JsonStore } from './settings.ts'
import { AppState } from './state.ts'
import { createMainWindow, isAllowedExternalUrl } from './window.ts'

const isDev = !app.isPackaged
app.setName(isDev ? 'PostHog Dev' : 'PostHog')
app.setPath('userData', path.join(app.getPath('appData'), isDev ? 'PostHog Desktop Dev' : 'PostHog Desktop'))

if (!app.requestSingleInstanceLock()) {
    app.quit()
} else {
    void main()
}

function resolveFrontendDistDir(): string {
    if (process.env.POSTHOG_DESKTOP_FRONTEND_DIST) {
        return process.env.POSTHOG_DESKTOP_FRONTEND_DIST
    }
    if (app.isPackaged) {
        return path.join(process.resourcesPath, 'frontend-dist')
    }
    // products/desktop/dist/main.js -> repo root -> frontend/dist
    return path.resolve(__dirname, '../../../frontend/dist')
}

async function main(): Promise<void> {
    const store = new JsonStore<DesktopSettings>(path.join(app.getPath('userData'), 'settings.json'), DEFAULT_SETTINGS)
    const distDir = resolveFrontendDistDir()
    const state = new AppState(store, {
        version: app.getVersion(),
        frontendBuilt: () => isFrontendBuilt(distDir),
    })

    await app.whenReady()

    let backend: LocalBackend
    try {
        backend = await startLocalBackend(
            {
                distDir,
                cacheDir: path.join(app.getPath('userData'), 'offline-cache'),
                getAuth: () => state.getAuth(),
                onSignOutRequested: () => {
                    state.signOut()
                    showShell()
                },
                upstreamHeaders: { 'user-agent': `PostHog-Desktop/${app.getVersion()}` },
            },
            store.get('port')
        )
    } catch (error) {
        dialog.showErrorBox('PostHog could not start', `The local server failed to start: ${error}`)
        app.quit()
        return
    }
    state.setAppOrigin(backend.origin)
    if (backend.port !== store.get('port')) {
        store.set({ port: backend.port })
    }

    const showShell = (): void => {
        void getWindow().loadFile(path.join(__dirname, 'shell/index.html'))
    }
    const showApp = (): void => {
        void getWindow().loadURL(`${backend.origin}/`)
    }
    const getWindow = (): BrowserWindow => {
        const existing = BrowserWindow.getAllWindows()[0]
        if (existing) {
            return existing
        }
        const win = createMainWindow(store)
        // A fresh window (e.g. macOS dock activate after closing) needs content again
        if (state.getAuth() && state.snapshot().frontendBuilt) {
            void win.loadURL(`${backend.origin}/`)
        } else {
            void win.loadFile(path.join(__dirname, 'shell/index.html'))
        }
        return win
    }

    registerIpcHandlers(state, { showShell, showApp })
    buildAppMenu({ showShell })

    app.on('second-instance', () => {
        const win = getWindow()
        if (win.isMinimized()) {
            win.restore()
        }
        win.focus()
    })
    app.on('activate', () => {
        getWindow().show()
    })
    app.on('window-all-closed', () => {
        if (process.platform !== 'darwin') {
            app.quit()
        }
    })
    app.on('web-contents-created', (_event, contents) => {
        contents.setWindowOpenHandler(({ url }) => {
            if (isAllowedExternalUrl(url)) {
                void shell.openExternal(url)
            }
            return { action: 'deny' }
        })
        contents.on('will-navigate', (event, url) => {
            const stayingLocal = url.startsWith(backend.origin) || url.startsWith('file://')
            if (!stayingLocal) {
                event.preventDefault()
                if (isAllowedExternalUrl(url)) {
                    void shell.openExternal(url)
                }
            }
        })
    })
    app.on('before-quit', () => {
        void backend.close().catch(() => {})
    })

    if (state.getAuth() && state.snapshot().frontendBuilt) {
        showApp()
    } else {
        showShell()
    }
}
