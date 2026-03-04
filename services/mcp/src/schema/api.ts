export interface ApiPropertyDefinition {
    id: string
    name: string
    description?: string | null | undefined
    is_numerical?: boolean | null | undefined
    updated_at?: string | null | undefined
    updated_by?: unknown
    is_seen_on_filtered_events?: boolean | null | undefined
    property_type?: 'String' | 'Numeric' | 'Boolean' | 'DateTime' | null | undefined
    verified?: boolean | null | undefined
    verified_at?: string | null | undefined
    verified_by?: unknown
    hidden?: boolean | null | undefined
    tags?: string[] | null | undefined
}

export interface ApiEventDefinition {
    id: string
    name: string
    owner?: string | null | undefined
    description?: string | null | undefined
    created_at?: string | null | undefined
    updated_at?: string | null | undefined
    updated_by?: unknown
    last_seen_at?: string | null | undefined
    verified?: boolean | null | undefined
    verified_at?: string | null | undefined
    verified_by?: unknown
    hidden?: boolean | null | undefined
    is_action?: boolean | null | undefined
    post_to_slack?: boolean | null | undefined
    default_columns?: Array<string | null | undefined> | null | undefined
    tags?: Array<string | null | undefined> | null | undefined
}

export interface ApiUser {
    distinct_id: string
    organizations: Array<{ id: string }>
    team: {
        id: number
        organization: string
    }
    organization: {
        id: string
    }
}

export interface ApiRedactedPersonalApiKey {
    scopes: string[]
    scoped_teams: number[]
    scoped_organizations: string[]
}

export type ApiOAuthIntrospection =
    | {
          active: true
          scope: string
          scoped_teams: number[]
          scoped_organizations: string[]
          client_name?: string
      }
    | {
          active: false
      }
