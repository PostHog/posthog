import api, { ApiConfig, CountedPaginatedResponse } from '~/lib/api'

import type { TraceReview, TraceReviewListParams, TraceReviewUpsertPayload } from './types'

function isRecord(value: unknown): value is Record<string, unknown> {
    return !!value && typeof value === 'object' && !Array.isArray(value)
}

function normalizeTraceReview(review: TraceReview): TraceReview {
    return {
        ...review,
        scores: Array.isArray(review.scores)
            ? review.scores.map((score) => ({
                  ...score,
                  definition_config: isRecord(score.definition_config) ? score.definition_config : {},
                  categorical_values: Array.isArray(score.categorical_values)
                      ? score.categorical_values.filter((value): value is string => typeof value === 'string')
                      : null,
              }))
            : [],
    }
}

function isDuplicateTraceReviewError(error: unknown): boolean {
    if (!error || typeof error !== 'object' || !('data' in error)) {
        return false
    }

    const { data } = error as { data?: unknown }

    return !!data && typeof data === 'object' && 'trace_id' in data
}

function getTraceReviewsBaseUrl(teamId: number = ApiConfig.getCurrentTeamId()): string {
    return `/api/environments/${teamId}/llm_analytics/trace_reviews/`
}

function buildTraceReviewsListUrl(
    teamId: number = ApiConfig.getCurrentTeamId(),
    params?: TraceReviewListParams
): string {
    const searchParams = new URLSearchParams()

    for (const [key, value] of Object.entries(params || {})) {
        if (value === undefined || value === null || value === '') {
            continue
        }

        if ((key === 'trace_id__in' || key === 'definition_id__in') && Array.isArray(value)) {
            if (value.length > 0) {
                searchParams.set(key, value.join(','))
            }
            continue
        }

        searchParams.set(key, String(value))
    }

    const query = searchParams.toString()
    return query ? `${getTraceReviewsBaseUrl(teamId)}?${query}` : getTraceReviewsBaseUrl(teamId)
}

export const traceReviewsApi = {
    list(
        params?: TraceReviewListParams,
        teamId: number = ApiConfig.getCurrentTeamId()
    ): Promise<CountedPaginatedResponse<TraceReview>> {
        return api
            .get<CountedPaginatedResponse<TraceReview>>(buildTraceReviewsListUrl(teamId, params))
            .then((response) => ({
                ...response,
                results: response.results.map(normalizeTraceReview),
            }))
    },

    async getByTraceId(traceId: string, teamId: number = ApiConfig.getCurrentTeamId()): Promise<TraceReview | null> {
        const response = await traceReviewsApi.list({ trace_id: traceId, limit: 1 }, teamId)
        return response.results[0] ?? null
    },

    create(data: TraceReviewUpsertPayload, teamId: number = ApiConfig.getCurrentTeamId()): Promise<TraceReview> {
        return api
            .create<TraceReview, TraceReviewUpsertPayload>(getTraceReviewsBaseUrl(teamId), data)
            .then(normalizeTraceReview)
    },

    update(
        id: string,
        data: Partial<Omit<TraceReviewUpsertPayload, 'trace_id'>>,
        teamId: number = ApiConfig.getCurrentTeamId()
    ): Promise<TraceReview> {
        return api
            .update<TraceReview, Partial<Omit<TraceReviewUpsertPayload, 'trace_id'>>>(
                `${getTraceReviewsBaseUrl(teamId)}${id}/`,
                data
            )
            .then(normalizeTraceReview)
    },

    delete(id: string, teamId: number = ApiConfig.getCurrentTeamId()): Promise<void> {
        return api.delete(`${getTraceReviewsBaseUrl(teamId)}${id}/`)
    },

    async save(
        data: TraceReviewUpsertPayload,
        existingReview: TraceReview | null,
        teamId: number = ApiConfig.getCurrentTeamId()
    ): Promise<TraceReview> {
        if (existingReview) {
            const { trace_id: _traceId, ...patchData } = data
            return traceReviewsApi.update(existingReview.id, patchData, teamId)
        }

        try {
            return await traceReviewsApi.create(data, teamId)
        } catch (error) {
            if (!isDuplicateTraceReviewError(error)) {
                throw error
            }

            const latestReview = await traceReviewsApi.getByTraceId(data.trace_id, teamId)

            if (latestReview) {
                const { trace_id: _traceId, ...patchData } = data
                return traceReviewsApi.update(latestReview.id, patchData, teamId)
            }

            throw error
        }
    },
}
