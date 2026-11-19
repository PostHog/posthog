import type { InboxItem } from '@/model/types'
import type { ProjectScope } from './reports'

export const LIVE_EXCLUDE_INTERNAL_CACHE_SUFFIX = 'exclude-internal'

export interface SavedInbox {
    items: InboxItem[]
    signalCounts?: Record<string, number>
    sourceUpdatedAt: number
}

export function inboxCacheKey(scope: ProjectScope | null): readonly unknown[] {
    return ['read-inbox', scope?.host ?? 'none', scope?.projectId ?? null]
}
