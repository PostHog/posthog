import type { AuthPolicy, IdentityConfig } from '@repo/ass-server/types'
/**
 * Fixture builders + cleanup tracker.
 *
 * Every helper here (a) writes to Postgres directly (the harness owns the
 * pools), (b) registers a teardown on the cluster's `CleanupRegistry` so the
 * suite's `afterAll` can wipe what it created without leaking state into the
 * next run.
 *
 * Slugs / names use the `e2e-…` prefix convention so a human can identify
 * test-created rows in the local DB and so accidental matches with real
 * data are vanishingly unlikely.
 */
import type { Pool } from 'pg'

const TEAM_ID = 1

export interface CleanupTask {
    description: string
    run(): Promise<void>
}

/**
 * Bag of teardown actions registered by fixture builders. `runAll` plays
 * them back in reverse order so dependents tear down before their parents
 * (identities → users → space → revisions → apps → team-secret restore).
 */
export class CleanupRegistry {
    private readonly tasks: CleanupTask[] = []

    constructor(private readonly pools: { posthog: Pool; queue: Pool }) {}

    register(task: CleanupTask): void {
        this.tasks.push(task)
    }

    async runAll(): Promise<void> {
        const errors: { description: string; error: unknown }[] = []
        for (const task of [...this.tasks].reverse()) {
            try {
                await task.run()
            } catch (error) {
                errors.push({ description: task.description, error })
            }
        }
        this.tasks.length = 0
        if (errors.length > 0) {
            // eslint-disable-next-line no-console
            console.warn('agent-tests cleanup had failures:', errors)
        }
    }

    get pool(): Pool {
        return this.pools.posthog
    }
    get queuePool(): Pool {
        return this.pools.queue
    }
}

/**
 * Set team 1's `secret_api_token` to a known value and register restore on
 * teardown. The default project's secret was probably NULL — we restore to
 * exactly whatever we found, so repeated runs are idempotent.
 */
export async function setTeamSecret(cleanup: CleanupRegistry, secret: string, teamId: number = TEAM_ID): Promise<void> {
    const { rows } = await cleanup.pool.query<{ secret_api_token: string | null }>(
        `SELECT secret_api_token FROM posthog_team WHERE id = $1`,
        [teamId]
    )
    if (rows.length === 0) {
        throw new Error(`setTeamSecret: team ${teamId} not found — is hogli's local DB seeded?`)
    }
    const prior = rows[0].secret_api_token
    if (prior === secret) {
        return
    }
    await cleanup.pool.query(`UPDATE posthog_team SET secret_api_token = $1 WHERE id = $2`, [secret, teamId])
    cleanup.register({
        description: `restore posthog_team(${teamId}).secret_api_token`,
        run: async () => {
            await cleanup.pool.query(`UPDATE posthog_team SET secret_api_token = $1 WHERE id = $2`, [prior, teamId])
        },
    })
}

export interface CreateAppInput {
    /** Local slug suffix; the actual slug is `e2e-<suffix>` for traceability. */
    slugSuffix: string
    /** The agent's `auth:` block (canonical {type, ...} shape — same as agent.yaml). */
    auth: AuthPolicy
    /** Optional `identity:` block — required for the slack identity tests. */
    identity?: IdentityConfig
    /** Triggers — defaults to a single `http_invoke`. Pass a Slack trigger explicitly. */
    triggers?: Array<Record<string, unknown>>
    /** Optional prompt — most e2e tests don't need it; defaults to a no-op marker. */
    prompt?: string
    /** Override team_id; defaults to 1 (the local default project). */
    teamId?: number
}

export interface CreatedApp {
    applicationId: string
    revisionId: string
    slug: string
}

/**
 * Insert an AgentApplication + an `live` `ready` AgentApplicationRevision
 * directly. Skips the deploy / validator pipeline — we're testing the
 * runtime, not the deploy flow.
 *
 * `top_level_config` is shaped like `agentDefinitionToAssYaml` emits so
 * `compileAgent` picks `auth` and `identity` up via the new manifest path.
 */
export async function createApp(cleanup: CleanupRegistry, input: CreateAppInput): Promise<CreatedApp> {
    const teamId = input.teamId ?? TEAM_ID
    const slug = `e2e-${input.slugSuffix}`
    // Idempotent — drop any prior fixture with this slug. Run in dependency
    // order: revisions → app (FK constraint).
    await cleanup.pool.query(
        `DELETE FROM agent_stack_agentapplicationrevision
         WHERE application_id IN (SELECT id FROM agent_stack_agentapplication WHERE slug = $1)`,
        [slug]
    )
    await cleanup.pool.query(`DELETE FROM agent_stack_agentapplication WHERE slug = $1`, [slug])

    const { rows: appRows } = await cleanup.pool.query<{ id: string }>(
        `INSERT INTO agent_stack_agentapplication
            (id, team_id, name, slug, description, deleted, created_at, updated_at)
         VALUES (gen_random_uuid(), $1, $2, $3, '', FALSE, NOW(), NOW())
         RETURNING id::text AS id`,
        [teamId, slug, slug]
    )
    const applicationId = appRows[0].id

    const manifest = {
        name: slug,
        slug,
        prompt: input.prompt ?? 'e2e fixture agent',
        visibility: 'private',
        auth: input.auth,
        identity: input.identity,
        triggers: input.triggers ?? [{ id: 'http', type: 'http_invoke' }],
        tools: [],
        skills: [],
        required_secrets: [],
    }

    const { rows: revRows } = await cleanup.pool.query<{ id: string }>(
        `INSERT INTO agent_stack_agentapplicationrevision
            (id, team_id, application_id, state, deployment_status, bundle_s3_key, bundle_size, bundle_sha256,
             top_level_config, parsed_manifest, created_at, updated_at)
         VALUES (gen_random_uuid(), $1, $2, 'ready', 'live', 's3://e2e', 0, '',
                 $3::jsonb, NULL, NOW(), NOW())
         RETURNING id::text AS id`,
        [teamId, applicationId, JSON.stringify(manifest)]
    )
    const revisionId = revRows[0].id

    cleanup.register({
        description: `delete app ${slug}`,
        run: async () => {
            // Cascade in dependency order: sessions (queue DB) → revisions → app.
            await cleanup.queuePool.query(`DELETE FROM agent_sessions WHERE application_id = $1`, [applicationId])
            await cleanup.pool.query(`DELETE FROM agent_stack_agentapplicationrevision WHERE application_id = $1`, [
                applicationId,
            ])
            await cleanup.pool.query(`DELETE FROM agent_stack_agentapplication WHERE id = $1`, [applicationId])
        },
    })
    return { applicationId, revisionId, slug }
}

export interface CreatedIdentitySpace {
    spaceId: string
    name: string
}

/**
 * Insert an `IdentitySpace` for the given team. Cleanup wipes the space
 * AND every `AgentUser` / `UserIdentity` row scoped to it — agents that
 * point at the space will have populated those during their session runs.
 */
export async function createIdentitySpace(
    cleanup: CleanupRegistry,
    name: string,
    teamId: number = TEAM_ID
): Promise<CreatedIdentitySpace> {
    await cleanup.pool.query(`DELETE FROM agent_stack_identityspace WHERE team_id = $1 AND name = $2`, [teamId, name])
    const { rows } = await cleanup.pool.query<{ id: string }>(
        `INSERT INTO agent_stack_identityspace (id, team_id, name, deleted, created_at, updated_at)
         VALUES (gen_random_uuid(), $1, $2, FALSE, NOW(), NOW())
         RETURNING id::text AS id`,
        [teamId, name]
    )
    const spaceId = rows[0].id
    cleanup.register({
        description: `delete identity space ${name}`,
        run: async () => {
            await cleanup.pool.query(`DELETE FROM agent_stack_useridentity WHERE space_id = $1`, [spaceId])
            await cleanup.pool.query(`DELETE FROM agent_stack_agentuser WHERE space_id = $1`, [spaceId])
            await cleanup.pool.query(`DELETE FROM agent_stack_identityspace WHERE id = $1`, [spaceId])
        },
    })
    return { spaceId, name }
}
