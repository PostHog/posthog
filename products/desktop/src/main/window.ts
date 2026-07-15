import { BrowserWindow } from 'electron'
import * as path from 'node:path'

import type { DesktopSettings, JsonStore, WindowBounds } from './settings.ts'

const DEFAULT_BOUNDS: WindowBounds = { width: 1440, height: 900 }

export function isAllowedExternalUrl(url: string): boolean {
    try {
        const parsed = new URL(url)
        return parsed.protocol === 'https:' || parsed.protocol === 'http:' || parsed.protocol === 'mailto:'
    } catch {
        return false
    }
}

export function createMainWindow(store: JsonStore<DesktopSettings>): BrowserWindow {
    const bounds = store.get('windowBounds') || DEFAULT_BOUNDS
    const win = new BrowserWindow({
        ...bounds,
        minWidth: 800,
        minHeight: 600,
        title: 'PostHog',
        backgroundColor: '#1d1f27',
        // On macOS the frontend renders edge to edge and reserves space for the
        // traffic lights itself (see the frontend's isDesktopAppMac() usages)
        ...(process.platform === 'darwin' ? { titleBarStyle: 'hiddenInset' as const } : {}),
        webPreferences: {
            preload: path.join(__dirname, 'preload.cjs'),
            contextIsolation: true,
            nodeIntegration: false,
            sandbox: true,
            partition: 'persist:main',
        },
    })

    const saveBounds = (): void => {
        if (!win.isDestroyed() && !win.isMinimized() && !win.isFullScreen()) {
            store.set({ windowBounds: win.getBounds() })
        }
    }
    win.on('close', saveBounds)
    win.on('moved', saveBounds)
    win.on('resized', saveBounds)

    return win
}
