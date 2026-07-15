/**
 * Holds the app's runtime state: settings plus the decrypted API key, which
 * lives only in main-process memory and is handed to the local backend's
 * proxy on demand. It is never exposed over IPC.
 */

import type { CloudRegion, DesktopState, DesktopStateSettings } from '../shared/ipc.ts'
import { resolveApiHost } from './regions.ts'
import { decryptSecret, encryptSecret } from './secrets.ts'
import type { UpstreamAuth } from './server/backend.ts'
import { type DesktopSettings, JsonStore } from './settings.ts'

export interface AppStateContext {
    version: string
    frontendBuilt: () => boolean
}

export class AppState {
    private readonly store: JsonStore<DesktopSettings>
    private readonly context: AppStateContext
    private apiKey: string | null = null
    private appOrigin: string | null = null

    constructor(store: JsonStore<DesktopSettings>, context: AppStateContext) {
        this.store = store
        this.context = context
        const encrypted = store.get('encryptedApiKey')
        if (encrypted) {
            this.apiKey = decryptSecret(encrypted)
        }
    }

    setAppOrigin(origin: string): void {
        this.appOrigin = origin
    }

    apiHost(): string | null {
        return resolveApiHost(this.store.get('region'), this.store.get('customHost'))
    }

    getAuth(): UpstreamAuth | null {
        const host = this.apiHost()
        if (!host || !this.apiKey) {
            return null
        }
        return { apiHost: host, accessToken: this.apiKey }
    }

    signIn(region: CloudRegion, customHost: string, apiKey: string, email: string): void {
        this.apiKey = apiKey
        this.store.set({
            region,
            customHost,
            encryptedApiKey: encryptSecret(apiKey),
            signedInEmail: email,
        })
    }

    signOut(): void {
        this.apiKey = null
        this.store.set({ encryptedApiKey: null, signedInEmail: null })
    }

    updateSettings(update: Partial<DesktopStateSettings>): void {
        const patch: Partial<DesktopSettings> = {}
        if (update.region) {
            patch.region = update.region
        }
        if (update.customHost !== undefined) {
            patch.customHost = update.customHost
        }
        this.store.set(patch)
    }

    snapshot(): DesktopState {
        return {
            version: this.context.version,
            platform: process.platform,
            settings: {
                region: this.store.get('region'),
                customHost: this.store.get('customHost'),
            },
            signedIn: this.getAuth() !== null,
            signedInEmail: this.store.get('signedInEmail'),
            apiHost: this.apiHost(),
            appOrigin: this.appOrigin,
            frontendBuilt: this.context.frontendBuilt(),
        }
    }
}
