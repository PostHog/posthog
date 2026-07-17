/**
 * Main-process entry point and composition root for the PostHog desktop app.
 *
 * Boot order matters: app identity (name + userData path) is set before any
 * other Electron API runs, so dev builds never share state with packaged ones
 * (pattern borrowed from posthog/code).
 */

import { app, BrowserWindow, dialog, shell } from 'electron'
import * as fs from 'node:fs'
import * as path from 'node:path'

import { registerIpcHandlers } from './ipc.ts'
import { buildAppMenu } from './menu.ts'
import { OAuthBrowserFlow } from './oauth.ts'
import { isFrontendBuilt, type LocalBackend, startLocalBackend } from './server/backend.ts'
import { type DesktopSettings, DEFAULT_SETTINGS, JsonStore } from './settings.ts'
import { AppState } from './state.ts'
import { AppUpdater } from './updates.ts'
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

/**
 * Additional app windows should open with a single tab (plus pinned tabs) instead of
 * cloning the whole restored tab set. The frontend strips this param at boot
 * (consumeDesktopFreshWindowParam in frontend/src/lib/utils/isDesktopApp.ts) and
 * sceneTabsLogic seeds the window's tabs accordingly.
 */
function markAsFreshWindow(url: string): string {
    try {
        const parsed = new URL(url)
        parsed.searchParams.set('__posthogDesktopFreshWindow', '1')
        return parsed.toString()
    } catch {
        return url
    }
}

/**
 * Headless capture hook for docs and visual checks: with
 * POSTHOG_DESKTOP_SCREENSHOT=/path/out.png the app captures the window after
 * it settles and quits. Delay is tunable via POSTHOG_DESKTOP_SCREENSHOT_DELAY_MS.
 */
function scheduleScreenshot(win: BrowserWindow): void {
    const outFile = process.env.POSTHOG_DESKTOP_SCREENSHOT
    if (!outFile) {
        return
    }
    const delayMs = Number(process.env.POSTHOG_DESKTOP_SCREENSHOT_DELAY_MS) || 3000
    win.webContents.on('did-finish-load', () => {
        setTimeout(() => {
            void win.webContents.capturePage().then((image) => {
                fs.writeFileSync(outFile, image.toPNG())
                console.info(`Saved screenshot to ${outFile}`)
                app.quit()
            })
        }, delayMs)
    })
}

async function main(): Promise<void> {
    const store = new JsonStore<DesktopSettings>(path.join(app.getPath('userData'), 'settings.json'), DEFAULT_SETTINGS)
    const distDir = resolveFrontendDistDir()
    const state = new AppState(store, {
        version: app.getVersion(),
        frontendBuilt: () => isFrontendBuilt(distDir),
    })

    await app.whenReady()

    const oauthFlow = new OAuthBrowserFlow()

    let backend: LocalBackend
    try {
        backend = await startLocalBackend(
            {
                distDir,
                cacheDir: path.join(app.getPath('userData'), 'offline-cache'),
                getAuth: () => state.getFreshAuth(),
                onOAuthCallback: (query) => oauthFlow.handleCallback(query),
                onSignOutRequested: () => {
                    state.signOut()
                    showShell()
                },
                onAuthRejected: () => {
                    void state.handleAuthRejected().then((signedOut) => {
                        if (signedOut) {
                            showShell()
                        }
                    })
                },
                upstreamHeaders: { 'user-agent': `PostHog-Desktop/${app.getVersion()}` },
                desktopVersion: app.getVersion(),
                desktopPlatform: process.platform,
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
        // Signed-out state is app-wide: collapse back to a single window showing the shell
        for (const win of BrowserWindow.getAllWindows().slice(1)) {
            win.close()
        }
        void getWindow().loadFile(path.join(__dirname, 'shell/index.html'))
    }
    const openAppWindow = (url: string): void => {
        const win = createMainWindow(store)
        scheduleScreenshot(win)
        void win.loadURL(markAsFreshWindow(url))
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
        scheduleScreenshot(win)
        // A fresh window (e.g. macOS dock activate after closing) needs content again
        if (state.getAuth() && state.snapshot().frontendBuilt) {
            void win.loadURL(`${backend.origin}/`)
        } else {
            void win.loadFile(path.join(__dirname, 'shell/index.html'))
        }
        return win
    }

    const updater = new AppUpdater()
    updater.start()

    registerIpcHandlers(state, oauthFlow, { showShell, showApp })
    buildAppMenu({
        showShell,
        newWindow: () => {
            if (state.getAuth() && state.snapshot().frontendBuilt) {
                openAppWindow(`${backend.origin}/`)
            }
        },
        checkForUpdates: () => updater.checkInteractively(),
    })

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
            // Local-origin URLs open a new PostHog window ("open in new window" in the
            // app, window.open, target=_blank on internal links); everything else goes
            // to the system browser
            if (url.startsWith(backend.origin) && state.getAuth()) {
                openAppWindow(url)
            } else if (isAllowedExternalUrl(url)) {
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
