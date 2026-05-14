import { EncryptedFields } from '../encryption'
import { logger } from '../logger'
import { PosthogDbClient } from './client'
import { ResolvedRevision } from './types'

export interface ApplicationsRepositoryOptions {
    db: PosthogDbClient
    /**
     * Optional decryptor for `agent_stack_agentapplication.encrypted_env`. Required by
     * `decryptEnv`. Ingress doesn't need it (only the runner ever reads env at tool
     * dispatch), so we leave it optional to keep the runtime split clean.
     */
    encryption?: EncryptedFields
}

interface ResolveRow {
    application_id: string
    application_slug: string
    team_id: number
    revision_id: string
    revision_state: ResolvedRevision['revisionState']
    bundle_s3_key: string
    bundle_sha256: string
    top_level_config: Record<string, unknown>
    parsed_manifest: Record<string, unknown> | null
}

interface EnvRow {
    encrypted_env: string | null
}

/**
 * Read-only access to the Django-owned application + revision tables.
 *
 * Replaces the HTTP InternalApiClient. Runtime services own no schema here; we read
 * `agent_stack_agentapplication` and `agent_stack_agentapplicationrevision` rows
 * directly. Live revisions are those with `deployment_status = 'live'` on a
 * non-deleted application.
 */
export class ApplicationsRepository {
    constructor(private readonly options: ApplicationsRepositoryOptions) {}

    /** Resolve by inbound host (e.g. `analytics-bot.agents.posthog.com`). */
    async resolveByDomain(domain: string, domainSuffix: string): Promise<ResolvedRevision | null> {
        if (!domain.endsWith(domainSuffix)) {
            return null
        }
        const slug = domain.slice(0, -domainSuffix.length)
        if (!slug) {
            return null
        }
        return this.resolveBySlug(slug)
    }

    async resolveBySlug(slug: string): Promise<ResolvedRevision | null> {
        return this.fetchOne('app.slug = $1', [slug])
    }

    async resolveById(applicationId: string): Promise<ResolvedRevision | null> {
        return this.fetchOne('app.id = $1', [applicationId])
    }

    /**
     * Returns the decrypted `encrypted_env` as a parsed Record<string,string>. v1 stores
     * the whole `.env` as one encrypted blob; we deserialize line-by-line with `=` as the
     * separator. Empty / null env → empty record.
     */
    async decryptEnv(applicationId: string): Promise<Record<string, string>> {
        if (!this.options.encryption) {
            throw new Error('ApplicationsRepository configured without an encryption decryptor')
        }
        const { rows } = await this.options.db.pool.query<EnvRow>(
            `SELECT encrypted_env FROM agent_stack_agentapplication WHERE id = $1 AND deleted = FALSE`,
            [applicationId]
        )
        if (rows.length === 0 || !rows[0].encrypted_env) {
            return {}
        }
        const plaintext = this.options.encryption.decrypt(rows[0].encrypted_env)
        if (!plaintext) {
            return {}
        }
        return parseDotenv(plaintext)
    }

    private async fetchOne(whereClause: string, params: unknown[]): Promise<ResolvedRevision | null> {
        const sql = `
            SELECT
                app.id::text          AS application_id,
                app.slug              AS application_slug,
                app.team_id           AS team_id,
                rev.id::text          AS revision_id,
                rev.state             AS revision_state,
                rev.bundle_s3_key     AS bundle_s3_key,
                rev.bundle_sha256     AS bundle_sha256,
                rev.top_level_config  AS top_level_config,
                rev.parsed_manifest   AS parsed_manifest
            FROM agent_stack_agentapplication app
            JOIN agent_stack_agentapplicationrevision rev
              ON rev.application_id = app.id
            WHERE ${whereClause}
              AND app.deleted = FALSE
              AND rev.deployment_status = 'live'
            LIMIT 1`
        let result
        try {
            result = await this.options.db.pool.query<ResolveRow>(sql, params)
        } catch (err) {
            logger.error('ApplicationsRepository fetch failed', { error: String(err), where: whereClause })
            throw err
        }
        if (result.rows.length === 0) {
            return null
        }
        return mapRow(result.rows[0])
    }
}

function mapRow(row: ResolveRow): ResolvedRevision {
    const auth = parseAuth(row.top_level_config)
    return {
        applicationId: row.application_id,
        applicationSlug: row.application_slug,
        teamId: row.team_id,
        revisionId: row.revision_id,
        revisionState: row.revision_state,
        bundleS3Key: row.bundle_s3_key,
        bundleSha256: row.bundle_sha256,
        topLevelConfig: row.top_level_config ?? {},
        parsedManifest: row.parsed_manifest,
        auth,
    }
}

function parseAuth(config: Record<string, unknown> | null): ResolvedRevision['auth'] {
    const raw = config && typeof config === 'object' ? (config as { auth?: unknown }).auth : undefined
    if (!raw || typeof raw !== 'object') {
        return { mode: 'public' }
    }
    const auth = raw as { mode?: string; token?: string; provider?: string; secret?: string }
    if (auth.mode === 'shared_secret' && typeof auth.token === 'string' && auth.token.length > 0) {
        return { mode: 'shared_secret', token: auth.token }
    }
    if (
        auth.mode === 'webhook_signature' &&
        typeof auth.provider === 'string' &&
        typeof auth.secret === 'string' &&
        auth.secret.length > 0
    ) {
        return { mode: 'webhook_signature', provider: auth.provider, secret: auth.secret }
    }
    return { mode: 'public' }
}

function parseDotenv(input: string): Record<string, string> {
    const result: Record<string, string> = {}
    for (const rawLine of input.split(/\r?\n/)) {
        const line = rawLine.trim()
        if (!line || line.startsWith('#')) {
            continue
        }
        const eq = line.indexOf('=')
        if (eq <= 0) {
            continue
        }
        const key = line.slice(0, eq).trim()
        let value = line.slice(eq + 1).trim()
        // Strip a single layer of matching quotes — same liberal parser Django uses.
        if ((value.startsWith('"') && value.endsWith('"')) || (value.startsWith("'") && value.endsWith("'"))) {
            value = value.slice(1, -1)
        }
        if (key) {
            result[key] = value
        }
    }
    return result
}
