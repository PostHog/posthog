import type { InsightApi } from '../../../product_analytics/frontend/generated/api.schemas'
import { ApiError, apiJson, projectPath } from './client'

export interface InsightSummary {
    name: string | null
    description: string | null
}
export async function getInsightSummary(shortId: string, signal?: AbortSignal): Promise<InsightSummary | null> {
    try {
        const insight = await apiJson<InsightApi>(projectPath(`insights/${encodeURIComponent(shortId)}/`), {
            query: { refresh: 'force_cache' },
            signal,
        })
        return { name: insight.name || insight.derived_name || null, description: insight.description || null }
    } catch (error) {
        if (error instanceof ApiError && error.status === 404) return null
        throw error
    }
}
