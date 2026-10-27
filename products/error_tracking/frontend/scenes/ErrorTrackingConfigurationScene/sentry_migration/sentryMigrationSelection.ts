import type { SentryMigrationItemApi, SentryMigrationRateLimitApi } from '../../../generated/api.schemas'

export function isSelectable(item: SentryMigrationItemApi): boolean {
    return item.fit !== 'unsupported' && !item.already_in_posthog
}

/** The rate limit whose Sentry window converts exactly, or else the first one PostHog can import. */
function closestRateLimit(items: SentryMigrationItemApi[]): SentryMigrationItemApi | undefined {
    // The project already has one of these limits, so another one would replace a match.
    if (items.some((item) => item.rate_limit && item.already_in_posthog)) {
        return undefined
    }
    const rateLimits = items.filter((item) => item.rate_limit && isSelectable(item))
    return rateLimits.find((item) => item.fit === 'good') ?? rateLimits[0]
}

/** Every suppression rule PostHog can add, and the one rate limit that matches Sentry most closely. */
export function defaultSelectedItemIds(items: SentryMigrationItemApi[]): string[] {
    const rateLimit = closestRateLimit(items)
    return items
        .filter((item) => isSelectable(item) && (item.rate_limit ? item === rateLimit : true))
        .map((item) => item.id)
}

export function itemDisabledReason(item: SentryMigrationItemApi): string | null {
    if (item.fit === 'unsupported') {
        return "PostHog can't import this setting"
    }
    if (item.already_in_posthog) {
        return item.built_in_filter
            ? 'This automatic suppression rule is already on'
            : 'This project already has this setting'
    }
    return null
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

export interface SentryImportPlan {
    rateLimit: SentryMigrationRateLimitApi | null
    manualRuleCount: number
    automaticRuleNames: string[]
}

/** What an import of the selected items changes in PostHog. */
export function buildImportPlan(items: SentryMigrationItemApi[], selectedItemIds: string[]): SentryImportPlan {
    const selected = items.filter((item) => selectedItemIds.includes(item.id) && isSelectable(item))
    return {
        rateLimit: selected.find((item) => item.rate_limit)?.rate_limit ?? null,
        manualRuleCount: selected.filter((item) => item.suppression_rule_filters).length,
        automaticRuleNames: selected.flatMap((item) => (item.built_in_filter ? [item.built_in_filter.name] : [])),
    }
}
