import type { UserBasicType } from '~/types'

import type {
    Kind01eEnumApi as ScoreDefinitionKind,
    ScoreDefinitionConfigApi as ScoreDefinitionConfig,
} from '../generated/api.schemas'

export type TraceReviewFormScoreValue = string | string[] | boolean | null

export interface TraceReviewScore {
    id: string
    definition_id: string
    definition_name: string
    definition_kind: ScoreDefinitionKind
    definition_archived: boolean
    definition_version_id: string
    definition_version: number
    definition_config: ScoreDefinitionConfig
    categorical_values: string[] | null
    numeric_value: string | null
    boolean_value: boolean | null
    created_at: string
    updated_at: string | null
}

export interface TraceReview {
    id: string
    trace_id: string
    comment: string | null
    created_at: string
    updated_at: string | null
    created_by: UserBasicType | null
    reviewed_by: UserBasicType | null
    scores: TraceReviewScore[]
    team: number
}

export interface TraceReviewScoreUpsertPayload {
    definition_id: string
    definition_version_id?: string | null
    categorical_values?: string[] | null
    numeric_value?: string | null
    boolean_value?: boolean | null
}

export interface TraceReviewUpsertPayload {
    trace_id: string
    queue_id?: string | null
    comment?: string | null
    scores: TraceReviewScoreUpsertPayload[]
}

export interface TraceReviewListParams {
    trace_id?: string
    trace_id__in?: string[]
    definition_id?: string
    definition_id__in?: string[]
    search?: string
    order_by?: string
    offset?: number
    limit?: number
}
