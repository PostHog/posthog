import * as Application from 'expo-application'
import Constants from 'expo-constants'
import * as Updates from 'expo-updates'

import { APP_VARIANTS, type AppVariant, isAppVariant, variantForAppId } from './appVariants'

export type { AppVariant } from './appVariants'

export type HostKind = 'cloud-us' | 'cloud-eu' | 'local' | 'custom'

const CLOUD_HOSTNAMES: Record<string, HostKind> = {
    'us.posthog.com': 'cloud-us',
    'eu.posthog.com': 'cloud-eu',
}

/**
 * The variant the native binary was built as. The bundle id comes first because an over-the-air update replaces
 * `extra`, and an update published with the wrong APP_VARIANT must not change what an installed build believes it is.
 * The web build has no bundle id and uses `extra`.
 */
export function resolveBuildVariant(appId: string | null | undefined, configVariant: unknown): AppVariant {
    return variantForAppId(appId) ?? (isAppVariant(configVariant) ? configVariant : 'production')
}

export const buildVariant: AppVariant = resolveBuildVariant(
    Application.applicationId,
    Constants.expoConfig?.extra?.appVariant
)

/** A bundle from Metro is development, even inside a binary built with the store identity. */
export const appVariant: AppVariant = __DEV__ ? 'development' : buildVariant

/** Dev and preview builds, and every Metro session. Store builds hide everything about environments. */
export const isInternalBuild: boolean = appVariant !== 'production'

/** The URL scheme the native build registers. It follows the binary, not Metro, so OAuth redirects reach the app. */
export const appScheme: string = APP_VARIANTS[buildVariant].scheme

export function isLoopbackHost(hostname: string): boolean {
    const bare = hostname.replace(/^\[|\]$/g, '').toLowerCase()
    return bare === 'localhost' || bare === '127.0.0.1' || bare === '::1'
}

export function hostKind(host: string): HostKind {
    let hostname: string
    try {
        hostname = new URL(host).hostname
    } catch {
        return 'custom'
    }
    return CLOUD_HOSTNAMES[hostname.toLowerCase()] ?? (isLoopbackHost(hostname) ? 'local' : 'custom')
}

export function isCloudHost(host: string): boolean {
    const kind = hostKind(host)
    return kind === 'cloud-us' || kind === 'cloud-eu'
}

// expo-updates has no channel or update in development builds and on the web, and can throw there.
function readUpdates(): { channel: string | null; id: string | null; createdAt: Date | null } {
    try {
        return { channel: Updates.channel || null, id: Updates.updateId ?? null, createdAt: Updates.createdAt ?? null }
    } catch {
        return { channel: null, id: null, createdAt: null }
    }
}

const updates = readUpdates()

export const updateChannel: string | null = updates.channel
/** Null when the app runs the JavaScript embedded in the binary, or a Metro bundle. */
export const updateId: string | null = updates.id
export const updateCreatedAt: Date | null = updates.createdAt

export type RibbonTone = 'development' | 'preview'

export interface EnvironmentBadge {
    tone: RibbonTone
    label: string
}

const VARIANT_LABELS: Record<RibbonTone, string> = {
    development: 'Dev build',
    preview: 'Preview build',
}

export function hostLabel(host: string): string {
    switch (hostKind(host)) {
        case 'cloud-us':
            return 'US cloud'
        case 'cloud-eu':
            return 'EU cloud'
        default:
            try {
                return new URL(host).host
            } catch {
                return host
            }
    }
}

/**
 * What the environment ribbon says, or null on a production build, which never shows the environment,
 * whatever host it talks to. `host` is null before sign-in picks one, or in demo mode without an account.
 */
export function environmentBadge(variant: AppVariant, host: string | null): EnvironmentBadge | null {
    if (variant === 'production') {
        return null
    }
    const label = host ? `${VARIANT_LABELS[variant]} · ${hostLabel(host)}` : VARIANT_LABELS[variant]
    return { tone: variant, label }
}
