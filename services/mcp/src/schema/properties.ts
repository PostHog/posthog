export interface PropertyDefinition {
    name: string
    property_type?: 'String' | 'Numeric' | 'Boolean' | 'DateTime' | null
}

export interface EventDefinition {
    name: string
    last_seen_at?: string | null
}
