export type SuppressionSource = 'BOUNCE' | 'MANUAL'

export interface SuppressionEntry {
    id: string
    identifier: string
    source: SuppressionSource
    reason: string | null
    transient_bounce_count: number
    last_bounce_at: string | null
    last_bounce_diagnostic: string | null
    suppressed: boolean
    suppressed_at: string | null
    created_at: string
    updated_at: string
}
