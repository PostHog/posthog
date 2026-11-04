import type { InboxItem } from '@/model/types'
import type { ProjectScope } from './reports'

export interface SavedInbox {
    items: InboxItem[]
    signalCounts?: Record<string, number>
    sourceUpdatedAt: number
}

export function inboxCacheKey(scope: ProjectScope | null): readonly unknown[] {
    return ['read-inbox', scope?.host ?? 'none', scope?.projectId ?? null]
}
