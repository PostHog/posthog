/**
 * Read-only access to PostHog's `posthog_integration` table — the same table
 * Settings → Integrations writes to and HogFunctions read from. Lets the
 * agent runner resolve `spec.integrations` to live OAuth credentials at
 * session start, and the agent ingress fetch the team's Slack bot token
 * when it needs to post (elevation message, owner-DM notification, etc.).
 *
 * The store does NOT cache. Reads are rare (once per session start in the
 * runner; once per rejected message in the ingress) and the underlying
 * Integration row may be rotated by the user at any time. If profiling
 * surfaces this as a hot path, slot in an LRU on top.
 *
 * Encryption: `posthog_integration.sensitive_config` is a Django
 * `EncryptedJSONField`, which `EncryptedFieldMixin.get_internal_type`
 * declares as TEXT in PG. So the on-disk format matches
 * `agent_application.encrypted_env` — Fernet ciphertext, base64 ASCII.
 * `EncryptedFields.decryptJson` handles the round-trip.
 */

import type { Pool } from 'pg'

import { EncryptedFields } from '../runtime/encryption'
import { IntegrationCredentials } from '../spec/tool'

export interface IntegrationRow {
    integration_id: string
    credentials: IntegrationCredentials
}

export interface IntegrationStore {
    /**
     * One row by natural key. Returns null when no row exists or the row's
     * sensitive_config can't be decrypted (key rotated past it, ignored on
     * the Python side via `ignore_decrypt_errors=True`).
     */
    get(team_id: number, kind: string, integration_id: string): Promise<IntegrationCredentials | null>
    /**
     * Every connected integration of one kind for one team. Most teams have
     * exactly one row per kind; multiples happen when a team connects two
     * Slack workspaces (etc.). Tools that take an explicit `team_integration_id`
     * use this list to find the right row.
     */
    list(team_id: number, kind: string): Promise<IntegrationRow[]>
    /**
     * Resolve every kind declared in a spec to its credentials map, keyed by
     * `<kind>:<integration_id>`. This is the shape `ToolContext.integrations`
     * expects — see the existing harness fixture in
     * services/agent-tests/src/cases/example-sre-bot.test.ts. Missing kinds
     * are silently omitted; the tool surfaces "integration not connected"
     * at call time.
     */
    resolveForSpec(team_id: number, specIntegrations: string[]): Promise<Record<string, IntegrationCredentials>>
}

function parseSensitiveConfig(raw: Record<string, unknown> | null, kind: string): IntegrationCredentials | null {
    if (!raw) {
        return null
    }
    const access_token = typeof raw.access_token === 'string' ? raw.access_token : ''
    if (!access_token) {
        // A row without an access token is unusable for the tool runtime; the
        // runner / ingress treat it like a missing integration.
        return null
    }
    const credentials: IntegrationCredentials = { kind, access_token }
    if (typeof raw.refresh_token === 'string') {
        credentials.refresh_token = raw.refresh_token
    }
    // Capture everything else under metadata so tools that need workspace ids
    // or scopes can read them without a second query.
    const metadata: Record<string, unknown> = {}
    for (const [k, v] of Object.entries(raw)) {
        if (k === 'access_token' || k === 'refresh_token') {
            continue
        }
        metadata[k] = v
    }
    if (Object.keys(metadata).length > 0) {
        credentials.metadata = metadata
    }
    return credentials
}

export class MemoryIntegrationStore implements IntegrationStore {
    private readonly rows: Array<{
        team_id: number
        kind: string
        integration_id: string
        credentials: IntegrationCredentials
    }> = []

    add(team_id: number, kind: string, integration_id: string, credentials: IntegrationCredentials): void {
        const i = this.rows.findIndex(
            (r) => r.team_id === team_id && r.kind === kind && r.integration_id === integration_id
        )
        const row = { team_id, kind, integration_id, credentials }
        if (i >= 0) {
            this.rows[i] = row
        } else {
            this.rows.push(row)
        }
    }

    async get(team_id: number, kind: string, integration_id: string): Promise<IntegrationCredentials | null> {
        const row = this.rows.find(
            (r) => r.team_id === team_id && r.kind === kind && r.integration_id === integration_id
        )
        return row?.credentials ?? null
    }

    async list(team_id: number, kind: string): Promise<IntegrationRow[]> {
        return this.rows
            .filter((r) => r.team_id === team_id && r.kind === kind)
            .map((r) => ({ integration_id: r.integration_id, credentials: r.credentials }))
    }

    async resolveForSpec(team_id: number, kinds: string[]): Promise<Record<string, IntegrationCredentials>> {
        const out: Record<string, IntegrationCredentials> = {}
        for (const kind of kinds) {
            for (const row of await this.list(team_id, kind)) {
                out[`${kind}:${row.integration_id}`] = row.credentials
            }
        }
        return out
    }
}

interface DbRow {
    integration_id: string | null
    sensitive_config: string | null
}

export class PgIntegrationStore implements IntegrationStore {
    constructor(
        private readonly pool: Pool,
        private readonly encryption: EncryptedFields
    ) {}

    async get(team_id: number, kind: string, integration_id: string): Promise<IntegrationCredentials | null> {
        const r = await this.pool.query<DbRow>(
            `SELECT integration_id, sensitive_config::text AS sensitive_config
             FROM posthog_integration
             WHERE team_id = $1 AND kind = $2 AND integration_id = $3
             LIMIT 1`,
            [team_id, kind, integration_id]
        )
        if (r.rowCount === 0) {
            return null
        }
        return this.decryptRow(kind, r.rows[0])
    }

    async list(team_id: number, kind: string): Promise<IntegrationRow[]> {
        const r = await this.pool.query<DbRow>(
            `SELECT integration_id, sensitive_config::text AS sensitive_config
             FROM posthog_integration
             WHERE team_id = $1 AND kind = $2
             ORDER BY integration_id`,
            [team_id, kind]
        )
        const out: IntegrationRow[] = []
        for (const row of r.rows) {
            if (!row.integration_id) {
                continue
            }
            const credentials = this.decryptRow(kind, row)
            if (credentials) {
                out.push({ integration_id: row.integration_id, credentials })
            }
        }
        return out
    }

    async resolveForSpec(team_id: number, kinds: string[]): Promise<Record<string, IntegrationCredentials>> {
        if (kinds.length === 0) {
            return {}
        }
        const r = await this.pool.query<{
            kind: string
            integration_id: string | null
            sensitive_config: string | null
        }>(
            `SELECT kind, integration_id, sensitive_config::text AS sensitive_config
             FROM posthog_integration
             WHERE team_id = $1 AND kind = ANY($2::text[])`,
            [team_id, kinds]
        )
        const out: Record<string, IntegrationCredentials> = {}
        for (const row of r.rows) {
            if (!row.integration_id) {
                continue
            }
            const credentials = this.decryptRow(row.kind, row)
            if (credentials) {
                out[`${row.kind}:${row.integration_id}`] = credentials
            }
        }
        return out
    }

    private decryptRow(kind: string, row: DbRow): IntegrationCredentials | null {
        if (!row.sensitive_config) {
            return null
        }
        try {
            const decoded = this.encryption.decryptJson(row.sensitive_config)
            return parseSensitiveConfig(decoded, kind)
        } catch {
            return null
        }
    }
}
