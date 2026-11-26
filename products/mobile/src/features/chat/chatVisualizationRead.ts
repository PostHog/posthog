import { ApiError } from '@/api/client'
import { readInsight } from '@/api/insights'
import { runQuery } from '@/api/query'
import type { ProjectScope } from '@/api/reports'
import { serverNow } from '@/api/serverClock'
import { cacheTargetPassed } from '@/features/views/freshness'
import { queryDisplay } from '@/features/views/snapshotChart'
import { hasGoodResult, insightSnapshot, isRateLimited } from '@/model/adapters/insightSnapshot'
import type { InsightSnapshot } from '@/model/views'
import { visualizationSnapshot, visualizationSource } from './visualizationModel'

interface VisualizationRead {
    query: unknown
    shortId?: string
    title?: string
    scope: ProjectScope | null
    signal: AbortSignal
    onCached?: (snapshot: InsightSnapshot | null) => void
}

async function savedVisualization({
    shortId,
    scope,
    signal,
    onCached,
}: VisualizationRead): Promise<InsightSnapshot | null> {
    if (!shortId) return null
    let cachedSnapshot: InsightSnapshot | undefined
    try {
        const cached = await readInsight({ shortId }, { refresh: 'force_cache', signal, scope })
        if (cached.short_id !== shortId) return null
        const now = Date.now()
        const snapshot = insightSnapshot(cached, undefined, { readAt: now, serverNow: serverNow() })
        if (hasGoodResult(cached)) {
            cachedSnapshot = snapshot
            onCached?.(snapshot)
        }
        if (queryDisplay(cached.query) === 'web' || (hasGoodResult(cached) && !cacheTargetPassed(snapshot)))
            return snapshot
        const computed = await readInsight({ id: cached.id, shortId }, { refresh: 'blocking', signal, scope })
        if (isRateLimited(computed)) throw new ApiError(429, {})
        if (!hasGoodResult(computed)) throw new Error('Insight data unavailable')
        return insightSnapshot(computed, snapshot, { readAt: Date.now(), serverNow: serverNow() })
    } catch (error) {
        if (error instanceof ApiError && [401, 403, 404].includes(error.status)) onCached?.(null)
        else if (cachedSnapshot) onCached?.({ ...cachedSnapshot, refreshFailed: true })
        if (error instanceof ApiError && error.status === 404) return null
        throw error
    }
}

export async function readChatVisualization(input: VisualizationRead): Promise<InsightSnapshot | null> {
    if (input.shortId) return savedVisualization(input)
    const response = await runQuery(visualizationSource(input.query), { signal: input.signal, scope: input.scope })
    const snapshot = visualizationSnapshot(input.query, response, input.title)
    if (!snapshot.lastRefreshAt) throw new Error('Chart data unavailable')
    return snapshot
}
