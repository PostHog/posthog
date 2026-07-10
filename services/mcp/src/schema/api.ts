import type { Schemas } from '@/api/generated'

export type ApiPropertyDefinition = Schemas.EnterprisePropertyDefinition
export type ApiEventDefinition = Schemas.EnterpriseEventDefinition

export interface ApiUser {
    distinct_id: string
    first_name?: string
    last_name?: string
    email: string
    organizations: Array<{ id: string; name: string }>
    // `team` and `organization` mirror the Django User's nullable `current_team`
    // / `current_organization` FKs — the `/api/users/@me/` serializer returns
    // `null` when the user has no current selection (e.g. newly provisioned
    // accounts or users who left their last org). Callers must null-check.
    team: {
        id: number
        name: string
        timezone: string
        organization: string
    } | null
    organization: {
        id: string
        name: string
        // `/api/users/@me/` embeds the full OrganizationSerializer for the
        // current org, so the consent flag is always present on the wire; it is
        // optional here because some tests construct partial users.
        is_ai_data_processing_approved?: boolean | null
        // `/api/users/@me/` embeds the full OrganizationSerializer, so the org's
        // plan entitlements ride along too; used by the fallback path when a
        // team-scoped token can't fetch the org directly.
        available_product_features?: Array<{ key: string }> | null
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
