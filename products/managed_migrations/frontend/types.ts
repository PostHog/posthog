export interface ManagedMigration {
    source: string
    api_key: string
    secret_key: string
    start_date: string
    end_date: string
    event_names_mode: 'all' | 'allow' | 'deny'
    event_names: string[]
}
