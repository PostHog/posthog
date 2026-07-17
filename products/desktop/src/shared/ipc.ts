/**
 * Types shared between the main process, the preload script, and the shell UI.
 * Keep this file dependency-free: it is bundled into all three contexts.
 */

export type CloudRegion = 'us' | 'eu' | 'custom'

export interface DesktopStateSettings {
    region: CloudRegion
    customHost: string
}

export type AuthMethod = 'api-key' | 'oauth'

export interface DesktopState {
    version: string
    platform: NodeJS.Platform
    settings: DesktopStateSettings
    signedIn: boolean
    signedInEmail: string | null
    /** How the current session authenticates, or null when signed out */
    authMethod: AuthMethod | null
    /** Which regions support "Sign in with browser" (OAuth client registered) */
    browserSignIn: Record<CloudRegion, boolean>
    /** Resolved API host for the active region, e.g. https://us.posthog.com */
    apiHost: string | null
    /** Origin of the local server that serves the PostHog app, e.g. http://127.0.0.1:48752 */
    appOrigin: string | null
    /** Whether frontend/dist exists, i.e. the PostHog frontend has been built */
    frontendBuilt: boolean
}

export interface SignInPayload {
    region: CloudRegion
    customHost?: string
    apiKey: string
}

export interface BrowserSignInPayload {
    region: CloudRegion
    customHost?: string
}

export type SignInResult = { ok: true; email: string } | { ok: false; error: string }

export interface DesktopApi {
    getState: () => Promise<DesktopState>
    signIn: (payload: SignInPayload) => Promise<SignInResult>
    signInWithBrowser: (payload: BrowserSignInPayload) => Promise<SignInResult>
    signOut: () => Promise<void>
    openApp: () => Promise<void>
    openExternal: (url: string) => Promise<void>
    updateSettings: (settings: Partial<DesktopStateSettings>) => Promise<DesktopState>
}

export const IPC_CHANNELS = {
    getState: 'desktop:get-state',
    signIn: 'desktop:sign-in',
    signInWithBrowser: 'desktop:sign-in-with-browser',
    signOut: 'desktop:sign-out',
    openApp: 'desktop:open-app',
    openExternal: 'desktop:open-external',
    updateSettings: 'desktop:update-settings',
} as const
