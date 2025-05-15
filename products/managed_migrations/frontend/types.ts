export interface ManagedMigration {
    source: string
    apiKey: string
    secretKey: string
    startDate: string
    endDate: string
    eventNamesMode: 'all' | 'allow' | 'deny'
    eventNames: string[]
}
