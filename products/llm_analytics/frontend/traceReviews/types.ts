import type { UserBasicType } from '~/types'

export type TraceReviewScoreKind = 'label' | 'numeric'
export type TraceReviewScoreLabel = 'good' | 'bad'
export type TraceReviewFormScoreMode = 'none' | TraceReviewScoreKind

export interface TraceReview {
    id: string
    trace_id: string
    score_kind: TraceReviewScoreKind | null
    score_label: TraceReviewScoreLabel | null
    score_numeric: string | null
    comment: string | null
    created_at: string
    updated_at: string | null
    created_by: UserBasicType | null
    reviewed_by: UserBasicType | null
    team: number
}

export interface TraceReviewUpsertPayload {
    trace_id: string
    score_kind: TraceReviewScoreKind | null
    score_label: TraceReviewScoreLabel | null
    score_numeric: string | null
    comment: string | null
}

export interface TraceReviewListParams {
    trace_id?: string
    trace_id__in?: string[]
    search?: string
    order_by?: string
    offset?: number
    limit?: number
}
