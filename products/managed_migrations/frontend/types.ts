export interface ManagedMigration {
    id: string
    source: string
    api_key: string
    secret_key: string
    start_date: string
    end_date: string
    event_names_mode: 'all' | 'allow' | 'deny'
    event_names: string[]
    status: 'Cancelled' | 'Completed' | 'Failed' | 'Running' | 'Starting'
    created_by: {
        id: number
        uuid: string
        distinct_id: string
        first_name: string
        email: string
    }
    created_at: string
    error: string | null
}
