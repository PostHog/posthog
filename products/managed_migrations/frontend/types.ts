export interface ManagedMigration {
    id: string
    source_type: 's3'
    s3_region: string
    s3_bucket: string
    s3_prefix: string
    access_key: string
    secret_key: string
    content_type: 'captured' | 'mixpanel' | 'amplitude'
    status: 'paused' | 'completed' | 'running' | 'failed'
    created_by: {
        id: number
        uuid: string
        distinct_id: string
        first_name: string
        email: string
    }
    created_at: string
    error: string | null
    state?: {
        parts?: Array<{
            key: string
            total_size: number | null
            current_offset: number
        }>
    }
}
