// The JSON form of one row. It mirrors the Python `IntegrationRecord`, plus `reference`, `version`,
// `legacy_id` and `is_source_row`. It never holds a secret.

import type { JsonObject } from '../crypto/canonical'
import type { IntegrationRow } from '../db/integrations'

export interface IntegrationRecordJson {
    id: string
    legacy_id: number | null
    /** The stored string form of a reference: the legacy id when the row has one, else the UUID. */
    reference: string
    team_id: number
    kind: string
    /** The id of the connection in the external system. */
    integration_id: string | null
    config: Record<string, unknown>
    errors: string
    created_at: string
    created_by_id: number | null
    auth_type: string
    display_name: string
    is_source_row: boolean
    version: number
}

export function referenceOf(row: IntegrationRow): string {
    return row.legacyId === null ? row.id : String(row.legacyId)
}

/** The name the UI shows. The provider registry can give a kind its own rule. */
export function displayName(row: IntegrationRow): string {
    const configured = row.config['display_name']
    if (typeof configured === 'string' && configured.length > 0) {
        return configured
    }
    return row.externalId ?? 'unknown ID'
}

export function toRecordJson(row: IntegrationRow): IntegrationRecordJson {
    return {
        id: row.id,
        legacy_id: row.legacyId,
        reference: referenceOf(row),
        team_id: row.ownerId,
        kind: row.kind,
        integration_id: row.externalId,
        config: row.config,
        errors: row.errors,
        created_at: row.createdAt.toISOString(),
        created_by_id: row.createdById,
        auth_type: row.authType,
        display_name: displayName(row),
        is_source_row: row.isSourceRow,
        version: row.version,
    }
}

const MAX_DATE_MS = 8.64e15

// Keys that stay in the service: it uses them to refresh tokens, and a caller never needs them.
const NEVER_EXPOSED: ReadonlySet<string> = new Set(['refresh_token'])
// An OAuth row's client secret is the app secret for the refresh. A `credentials` row (Databricks
// service principals, say) needs its client secret to authenticate, so it is returned.
const NEVER_EXPOSED_OAUTH: ReadonlySet<string> = new Set([...NEVER_EXPOSED, 'client_secret'])

/**
 * The part of a decrypted secret blob that `resolve` returns. The provider registry can narrow
 * this per kind. It never widens it past `NEVER_EXPOSED`.
 */
export function exposedCredentials(authType: string, blob: JsonObject): JsonObject {
    const hidden = authType === 'oauth' ? NEVER_EXPOSED_OAUTH : NEVER_EXPOSED
    const exposed: JsonObject = {}
    for (const [key, value] of Object.entries(blob)) {
        if (!hidden.has(key)) {
            exposed[key] = value
        }
    }
    return exposed
}

/**
 * When the stored access token expires: `refreshed_at + expires_in` from the config, the fields
 * the Django OAuth code writes. Null when the row does not store both.
 */
export function tokenExpiresAt(row: IntegrationRow): string | null {
    const refreshedAt = row.config['refreshed_at']
    const expiresIn = row.config['expires_in']
    if (typeof refreshedAt !== 'number' || typeof expiresIn !== 'number') {
        return null
    }
    const expiresAtMs = (refreshedAt + expiresIn) * 1000
    // A Date holds at most 8.64e15 ms either side of the epoch. toISOString throws past that.
    return Math.abs(expiresAtMs) <= MAX_DATE_MS ? new Date(expiresAtMs).toISOString() : null
}
