import type { Schemas } from '@/api/generated'

export type ApiPropertyDefinition = Schemas.EnterprisePropertyDefinition
export type ApiEventDefinition = Schemas.EnterpriseEventDefinition

export interface ApiUser {
    distinct_id: string
    first_name?: string
    last_name?: string
    email: string
    organizations: Array<{ id: string; name: string }>
    team: {
        id: number
        name: string
        timezone: string
        organization: string
    }
    organization: {
        id: string
        name: string
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
