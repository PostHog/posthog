/**
 * Holds the app's runtime state: settings plus the decrypted credentials,
 * which live only in main-process memory and are handed to the local backend's
 * proxy on demand. They are never exposed over IPC.
 *
 * Two auth methods coexist: a pasted personal API key (phx_...), or an OAuth
 * session from the browser sign-in (pha_ access + phr_ refresh token). The
 * proxy calls getFreshAuth() per request, which transparently refreshes the
 * OAuth access token shortly before it expires.
 */

import type { AuthMethod, CloudRegion, DesktopState, DesktopStateSettings } from '../shared/ipc.ts'
import { REFRESH_MARGIN_MS, refreshAccessToken, type TokenSet, oauthClientIdFor } from './oauth.ts'
import { resolveApiHost } from './regions.ts'
import { decryptSecret, encryptSecret } from './secrets.ts'
import type { UpstreamAuth } from './server/backend.ts'
import { type DesktopSettings, JsonStore } from './settings.ts'

export interface AppStateContext {
    version: string
    frontendBuilt: () => boolean
}

interface OAuthSession {
    accessToken: string
    refreshToken: string
    expiresAt: number
    clientId: string
}

export class AppState {
    private readonly store: JsonStore<DesktopSettings>
    private readonly context: AppStateContext
    private apiKey: string | null = null
    private oauth: OAuthSession | null = null
    private authLoaded = false
    private appOrigin: string | null = null
    private refreshInFlight: Promise<UpstreamAuth | null> | null = null

    constructor(store: JsonStore<DesktopSettings>, context: AppStateContext) {
        this.store = store
        this.context = context
    }

    /**
     * Decrypts stored credentials lazily, on first getAuth(). AppState is constructed before
     * app.whenReady(), and Electron's safeStorage throws when used before the app is ready —
     * eager decryption in the constructor silently signed the user out on every launch.
     */
    private loadAuth(): void {
        if (this.authLoaded) {
            return
        }
        this.authLoaded = true
        const encryptedApiKey = this.store.get('encryptedApiKey')
        if (encryptedApiKey) {
            this.apiKey = decryptSecret(encryptedApiKey)
            return
        }
        const encryptedRefresh = this.store.get('encryptedOauthRefreshToken')
        const clientId = this.store.get('oauthClientId')
        if (encryptedRefresh && clientId) {
            const refreshToken = decryptSecret(encryptedRefresh)
            const encryptedAccess = this.store.get('encryptedOauthAccessToken')
            const accessToken = encryptedAccess ? decryptSecret(encryptedAccess) : null
            if (refreshToken) {
                this.oauth = {
                    refreshToken,
                    accessToken: accessToken || '',
                    expiresAt: this.store.get('oauthExpiresAt') || 0,
                    clientId,
                }
            }
        }
    }

    setAppOrigin(origin: string): void {
        this.appOrigin = origin
    }

    apiHost(): string | null {
        return resolveApiHost(this.store.get('region'), this.store.get('customHost'))
    }

    authMethod(): AuthMethod | null {
        this.loadAuth()
        if (this.apiKey) {
            return 'api-key'
        }
        if (this.oauth) {
            return 'oauth'
        }
        return null
    }

    /** Last-known auth, without refreshing. The OAuth access token may be expired. */
    getAuth(): UpstreamAuth | null {
        this.loadAuth()
        const host = this.apiHost()
        if (!host) {
            return null
        }
        if (this.apiKey) {
            return { apiHost: host, accessToken: this.apiKey }
        }
        if (this.oauth?.accessToken) {
            return { apiHost: host, accessToken: this.oauth.accessToken }
        }
        return null
    }

    /** Auth for an upstream request, refreshing the OAuth access token when it is about to expire. */
    async getFreshAuth(): Promise<UpstreamAuth | null> {
        this.loadAuth()
        if (!this.oauth || this.oauth.expiresAt - Date.now() > REFRESH_MARGIN_MS) {
            return this.getAuth()
        }
        this.refreshInFlight ??= this.refreshOAuth().finally(() => {
            this.refreshInFlight = null
        })
        return await this.refreshInFlight
    }

    /**
     * Called when the upstream rejects the current credentials (401 on @me).
     * For OAuth this forces one refresh attempt first — an expired access token
     * is recoverable, only a rejected refresh token means the session is dead.
     * Returns true when the app should sign out.
     */
    async handleAuthRejected(): Promise<boolean> {
        this.loadAuth()
        if (this.oauth) {
            this.oauth.expiresAt = 0
            const auth = await this.getFreshAuth()
            if (auth) {
                return false
            }
            // A transient refresh failure right after an upstream 401 still strands the
            // user, so treat any failed forced refresh as terminal
            this.signOut()
            return true
        }
        this.signOut()
        return true
    }

    private async refreshOAuth(): Promise<UpstreamAuth | null> {
        const host = this.apiHost()
        if (!host || !this.oauth) {
            return null
        }
        const result = await refreshAccessToken({
            apiHost: host,
            clientId: this.oauth.clientId,
            refreshToken: this.oauth.refreshToken,
        })
        if (result.ok) {
            this.oauth = { ...this.oauth, ...result.tokens }
            this.store.set({
                encryptedOauthRefreshToken: encryptSecret(result.tokens.refreshToken),
                encryptedOauthAccessToken: encryptSecret(result.tokens.accessToken),
                oauthExpiresAt: result.tokens.expiresAt,
            })
            return { apiHost: host, accessToken: result.tokens.accessToken }
        }
        if (result.terminal) {
            this.signOut()
            return null
        }
        // Transient failure (offline, 5xx): hand back the stale token so offline
        // cache serving keeps working; the next request retries the refresh
        return this.getAuth()
    }

    signIn(region: CloudRegion, customHost: string, apiKey: string, email: string): void {
        this.apiKey = apiKey
        this.oauth = null
        this.authLoaded = true
        this.store.set({
            region,
            customHost,
            encryptedApiKey: encryptSecret(apiKey),
            encryptedOauthRefreshToken: null,
            encryptedOauthAccessToken: null,
            oauthExpiresAt: null,
            oauthClientId: null,
            signedInEmail: email,
        })
    }

    signInOAuth(region: CloudRegion, customHost: string, tokens: TokenSet, clientId: string, email: string): void {
        this.apiKey = null
        this.oauth = { ...tokens, clientId }
        this.authLoaded = true
        this.store.set({
            region,
            customHost,
            encryptedApiKey: null,
            encryptedOauthRefreshToken: encryptSecret(tokens.refreshToken),
            encryptedOauthAccessToken: encryptSecret(tokens.accessToken),
            oauthExpiresAt: tokens.expiresAt,
            oauthClientId: clientId,
            signedInEmail: email,
        })
    }

    signOut(): void {
        this.apiKey = null
        this.oauth = null
        this.authLoaded = true
        this.store.set({
            encryptedApiKey: null,
            encryptedOauthRefreshToken: null,
            encryptedOauthAccessToken: null,
            oauthExpiresAt: null,
            oauthClientId: null,
            signedInEmail: null,
        })
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
            authMethod: this.authMethod(),
            browserSignIn: {
                us: oauthClientIdFor('us') !== null,
                eu: oauthClientIdFor('eu') !== null,
                custom: oauthClientIdFor('custom') !== null,
            },
            apiHost: this.apiHost(),
            appOrigin: this.appOrigin,
            frontendBuilt: this.context.frontendBuilt(),
        }
    }
}
