/**
 * Preload for every page in the main window (the shell UI and the PostHog app
 * itself). Exposes a deliberately small, promise-based API; no Node or
 * Electron objects ever cross the bridge.
 */

import { contextBridge, ipcRenderer } from 'electron'

import {
    type BrowserSignInPayload,
    type DesktopApi,
    type DesktopStateSettings,
    IPC_CHANNELS,
    type SignInPayload,
} from '../shared/ipc.ts'

const api: DesktopApi = {
    getState: () => ipcRenderer.invoke(IPC_CHANNELS.getState),
    signIn: (payload: SignInPayload) => ipcRenderer.invoke(IPC_CHANNELS.signIn, payload),
    signInWithBrowser: (payload: BrowserSignInPayload) => ipcRenderer.invoke(IPC_CHANNELS.signInWithBrowser, payload),
    signOut: () => ipcRenderer.invoke(IPC_CHANNELS.signOut),
    openApp: () => ipcRenderer.invoke(IPC_CHANNELS.openApp),
    openExternal: (url: string) => ipcRenderer.invoke(IPC_CHANNELS.openExternal, url),
    updateSettings: (settings: Partial<DesktopStateSettings>) =>
        ipcRenderer.invoke(IPC_CHANNELS.updateSettings, settings),
}

contextBridge.exposeInMainWorld('posthogDesktop', api)
