import type { Schemas } from '@/api/generated'

export type ApiPropertyDefinition = Schemas.EnterprisePropertyDefinition
export type ApiEventDefinition = Schemas.EnterpriseEventDefinition

export interface ApiUser {
    distinct_id: string
    first_name?: string
    last_name?: string
    email: string
    organizations: Array<{ id: string; name: string }>
    // `team` and `organization` come from the user's `current_team` /
    // `current_organization` FKs, both of which are nullable on the Django
    // model (`SET_NULL`). The API returns `null` for users without an active
    // workspace — callers must null-check before reading `.id`.
    team: {
        id: number
        name: string
        timezone: string
        organization: string
    } | null
    organization: {
        id: string
        name: string
    } | null
}

// `scoped_teams` and `scoped_organizations` arrive from the API as either an
// array or `null` (DRF serializer default). Callers must normalize null to []
// at the wire boundary (see `StateManager._fetchApiKey`); this type represents
// the post-normalization shape that the rest of the codebase consumes.
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
