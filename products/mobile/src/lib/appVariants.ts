import table from './appVariants.json'

// The table is JSON because app.config.ts reads it too, and the Expo config loader cannot import TypeScript modules.

export type AppVariant = 'development' | 'preview' | 'production'

export interface AppVariantConfig {
    name: string
    /** Appended to the production bundle id and Android package, so the variants install side by side. */
    idSuffix: string
    scheme: string
}

export const APP_VARIANTS: Record<AppVariant, AppVariantConfig> = table.variants

export function isAppVariant(value: unknown): value is AppVariant {
    return typeof value === 'string' && Object.hasOwn(APP_VARIANTS, value)
}

export function appIdFor(variant: AppVariant, platform: 'ios' | 'android'): string {
    return `${table.productionAppIds[platform]}${APP_VARIANTS[variant].idSuffix}`
}

/** The variant a native bundle id or Android package belongs to, or null for an id this app never builds. */
export function variantForAppId(appId: string | null | undefined): AppVariant | null {
    if (!appId) {
        return null
    }
    return (
        (Object.keys(APP_VARIANTS) as AppVariant[]).find(
            (variant) => appIdFor(variant, 'ios') === appId || appIdFor(variant, 'android') === appId
        ) ?? null
    )
}
