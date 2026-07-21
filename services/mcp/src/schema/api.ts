import type { Schemas } from '@/api/generated'

export type ApiPropertyDefinition = Schemas.EnterprisePropertyDefinition
export type ApiEventDefinition = Schemas.EnterpriseEventDefinition

export interface ApiUser {
    distinct_id: string
    first_name?: string
    last_name?: string
    email: string
    // Gates discovery of staff-only tools (those requiring an OAUTH_SCOPES_HIDDEN
    // scope). Optional because some tests construct partial users; treat absence
    // as not staff.
    is_staff?: boolean
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
// at the wire boundary (see `StateManager._fetchAuthorizationMetadata`); this
// type represents the post-normalization shape that the rest of the codebase
// consumes.
export interface ApiRedactedPersonalApiKey {
    scopes: string[]
    scoped_teams: number[]
    scoped_organizations: string[]
}

// Resource-server-authoritative authorization for the request's bearer, served
// from `/api/users/@me/effective_authorization/`. This is the single source of
// truth for every credential type (including ID-JAG access tokens, whose scopes
// can't be resolved via the personal-key lookup or OAuth introspection). `null`
// means unrestricted; callers normalize null to [] at the boundary.
//
// Bound to the OpenAPI-generated schema (regenerated from the backend serializer
// by `build:openapi`) rather than hand-declared, so a backend field or nullability
// change breaks MCP at compile time instead of drifting silently — the two sides
// of the contract can't diverge.
export type ApiEffectiveAuthorization = Schemas.EffectiveAuthorization

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
