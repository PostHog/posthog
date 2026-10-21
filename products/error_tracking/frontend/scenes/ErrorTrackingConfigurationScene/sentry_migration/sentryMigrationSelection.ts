import type { SentryMigrationItemApi } from '../../../generated/api.schemas'

export function isSelectable(item: SentryMigrationItemApi): boolean {
    return item.fit !== 'unsupported' && !item.already_in_posthog
}

/** Every suppression rule PostHog can add. A rate limit replaces the project's current one, so the user picks it on purpose. */
export function defaultSelectedItemIds(items: SentryMigrationItemApi[]): string[] {
    return items.filter((item) => isSelectable(item) && !item.rate_limit).map((item) => item.id)
}

export function toggleItemSelection(items: SentryMigrationItemApi[], selectedIds: string[], itemId: string): string[] {
    if (selectedIds.includes(itemId)) {
        return selectedIds.filter((id) => id !== itemId)
    }
    const item = items.find((candidate) => candidate.id === itemId)
    if (!item || !isSelectable(item)) {
        return selectedIds
    }
    if (!item.rate_limit) {
        return [...selectedIds, itemId]
    }
    const rateLimitIds = new Set(items.filter((candidate) => candidate.rate_limit).map((candidate) => candidate.id))
    return [...selectedIds.filter((id) => !rateLimitIds.has(id)), itemId]
}
