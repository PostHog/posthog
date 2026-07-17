/**
 * Minimal typed JSON settings store (a hand-rolled electron-store) persisted in
 * the app's userData directory. Everything here works fully offline.
 */

import * as fs from 'node:fs'
import * as path from 'node:path'

import type { CloudRegion } from '../shared/ipc.ts'

export interface WindowBounds {
    x?: number
    y?: number
    width: number
    height: number
}

export interface DesktopSettings {
    region: CloudRegion
    customHost: string
    /** Preferred local backend port; kept stable so renderer localStorage survives restarts */
    port: number
    windowBounds: WindowBounds | null
    /** Personal API key, encrypted with Electron safeStorage (see secrets.ts) */
    encryptedApiKey: string | null
    /** OAuth refresh token (phr_...), encrypted with Electron safeStorage */
    encryptedOauthRefreshToken: string | null
    /** Last OAuth access token (pha_...), encrypted; kept so offline boots still have an auth to attach */
    encryptedOauthAccessToken: string | null
    /** Epoch ms when the stored OAuth access token expires */
    oauthExpiresAt: number | null
    /** OAuth client the stored tokens were issued to */
    oauthClientId: string | null
    signedInEmail: string | null
}

export const DEFAULT_SETTINGS: DesktopSettings = {
    region: 'us',
    customHost: '',
    port: 48752,
    windowBounds: null,
    encryptedApiKey: null,
    encryptedOauthRefreshToken: null,
    encryptedOauthAccessToken: null,
    oauthExpiresAt: null,
    oauthClientId: null,
    signedInEmail: null,
}

export class JsonStore<T extends object> {
    private readonly filePath: string
    private data: T

    constructor(filePath: string, defaults: T) {
        this.filePath = filePath
        this.data = { ...defaults }
        try {
            const raw = fs.readFileSync(filePath, 'utf8')
            this.data = { ...defaults, ...JSON.parse(raw) }
        } catch (error) {
            if ((error as NodeJS.ErrnoException).code !== 'ENOENT') {
                console.warn(`Could not read settings file at ${filePath}, using defaults`, error)
            }
        }
    }

    get<K extends keyof T>(key: K): T[K] {
        return this.data[key]
    }

    all(): T {
        return { ...this.data }
    }

    set(update: Partial<T>): void {
        this.data = { ...this.data, ...update }
        this.persist()
    }

    private persist(): void {
        try {
            fs.mkdirSync(path.dirname(this.filePath), { recursive: true })
            const tmpPath = `${this.filePath}.tmp`
            fs.writeFileSync(tmpPath, JSON.stringify(this.data, null, 2))
            fs.renameSync(tmpPath, this.filePath)
        } catch (error) {
            console.error(`Could not write settings file at ${this.filePath}`, error)
        }
    }
}
