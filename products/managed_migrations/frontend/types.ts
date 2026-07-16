export type ManagedMigrationStatus = 'paused' | 'completed' | 'running' | 'failed' | 'waiting_to_start'

export interface TrialSummary {
    source_records: number
    output_events: number
    dropped_records: number
    skipped_records: number
    event_name_counts: Record<string, number>
    error_counts: Record<string, number>
    first_timestamp?: string
    last_timestamp?: string
}

export interface TrialProgress {
    records_emitted: number
    pages_written: number
    summary: TrialSummary
}

export interface TrialOutputEvent {
    uuid: string
    distinct_id: string
    event: string
    timestamp?: string
    payload: unknown
}

export interface TrialRecord {
    seq: number
    source: unknown
    outputs: TrialOutputEvent[]
    error?: string | null
}

export interface BaseManagedMigration {
    id: string
    access_key: string
    secret_key: string
    content_type: 'captured' | 'mixpanel' | 'amplitude'
    status: ManagedMigrationStatus
    display_status: ManagedMigrationStatus
    is_trial: boolean
    trial_record_limit: number | null
    created_by: {
        id: number
        uuid: string
        distinct_id: string
        first_name: string
        email: string
    }
    created_at: string
    status_message: string | null
    state?: {
        parts?: Array<{
            key: string
            total_size: number | null
            current_offset: number
        }>
        trial?: TrialProgress
    }
}

export interface S3ManagedMigration extends BaseManagedMigration {
    source_type: 's3'
    s3_region: string
    s3_bucket: string
    s3_prefix: string
    endpoint_url?: string
}

export interface S3GzipManagedMigration extends BaseManagedMigration {
    source_type: 's3_gzip'
    s3_region: string
    s3_bucket: string
    s3_prefix: string
    endpoint_url?: string
}

export interface DateRangeManagedMigration extends BaseManagedMigration {
    source_type: 'mixpanel' | 'amplitude' | 'date_range_export'
    start_date: string
    end_date: string
}

export type ManagedMigration = S3ManagedMigration | S3GzipManagedMigration | DateRangeManagedMigration
