export type WatchPicksVariant = 'in-list' | 'watch-tab' | 'both'

export function watchPicksVariantFromFlag(value: string | boolean | undefined): WatchPicksVariant | null {
    return value === 'in-list' || value === 'watch-tab' || value === 'both' ? value : null
}
