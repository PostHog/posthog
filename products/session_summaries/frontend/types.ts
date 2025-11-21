import { UserBasicType } from '~/types'

// Matches _SeverityLevel enum from ee/hogai/session_summaries/session_group/patterns.py
export type SeverityLevel = 'low' | 'medium' | 'high' | 'critical'

// Matches EnrichedPatternAssignedEvent from patterns.py
export interface EnrichedPatternAssignedEvent {
    event_id: string
    event_uuid: string
    session_id: string
    description: string
    abandonment: boolean
    confusion: boolean
    exception: string | null
    timestamp: string
    milliseconds_since_start: number
    window_id: string | null
    current_url: string | null
    event: string
    event_type: string | null
    event_index: number
}

// Matches PatternAssignedEventSegmentContext from patterns.py
export interface PatternAssignedEventSegmentContext {
    segment_name: string
    segment_outcome: string
    segment_success: boolean
    segment_index: number
    previous_events_in_segment: EnrichedPatternAssignedEvent[]
    target_event: EnrichedPatternAssignedEvent
    next_events_in_segment: EnrichedPatternAssignedEvent[]
    session_start_time_str: string | null
    session_duration: number | null
    person_distinct_ids: string[]
    person_email: string | null
}

// Matches EnrichedSessionGroupSummaryPatternStats from patterns.py
export interface EnrichedSessionGroupSummaryPatternStats {
    occurences: number
    sessions_affected: number
    sessions_affected_ratio: number
    segments_success_ratio: number
}

// Matches EnrichedSessionGroupSummaryPattern from patterns.py
export interface EnrichedSessionGroupSummaryPattern {
    pattern_id: number
    pattern_name: string
    pattern_description: string
    severity: SeverityLevel
    indicators: string[]
    events: PatternAssignedEventSegmentContext[]
    stats: EnrichedSessionGroupSummaryPatternStats
}

// Matches EnrichedSessionGroupSummaryPatternsList from patterns.py
export interface EnrichedSessionGroupSummaryPatternsList {
    patterns: EnrichedSessionGroupSummaryPattern[]
}

export type SessionGroupSummaryListItemType = {
    id: string
    title: string
    session_count: number
    created_at: string
    created_by: UserBasicType | null
}

export type SessionGroupSummaryType = SessionGroupSummaryListItemType & {
    session_ids: string[]
    summary: string
    extra_summary_context: Record<string, any> | null
    run_metadata: Record<string, any> | null
    team: number
}
