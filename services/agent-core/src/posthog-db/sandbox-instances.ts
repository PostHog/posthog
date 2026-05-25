import { PosthogDbClient } from './client'

export interface SandboxInstancesRepositoryOptions {
    db: PosthogDbClient
}

export type SandboxState = 'provisioning' | 'ready' | 'terminating' | 'terminated'

export interface SandboxInstanceRow {
    id: string
    state: SandboxState
}

/**
 * Row shape the janitor needs to dispatch to the right provider terminator.
 * `providerKind` is inferred from `providerSandboxId` shape — Docker container
 * ids are 64-char hex, Modal sandbox ids look like `sb-…`. A `provider_kind`
 * column is the v2 answer; the field shape is already sufficient for v1.
 */
export interface StaleSandboxRow extends SandboxInstanceRow {
    providerSandboxId: string
    providerKind: 'docker' | 'modal'
}

function inferProviderKind(providerSandboxId: string): 'docker' | 'modal' {
    return /^[0-9a-f]{40,}$/i.test(providerSandboxId) ? 'docker' : 'modal'
}

/**
 * Durable lifecycle log for tool sandboxes. Backs the `SandboxTracker`
 * interface in @repo/ass-sandbox: every Docker container / Modal sandbox the
 * runner creates leaves a row here so a sibling worker (or the janitor) can
 * reap orphans after a crash. The Docker provider also has in-process labels
 * + an age-based reaper; this layer is the multi-worker / Modal-shaped answer.
 *
 * The Django model's `modal_sandbox_id` column predates the multi-provider
 * design — it stores the docker container id for Docker sandboxes too. v2
 * will rename it to `provider_sandbox_id`; the storage shape is already right.
 */
export class SandboxInstancesRepository {
    constructor(private readonly options: SandboxInstancesRepositoryOptions) {}

    /**
     * Insert a new row in `provisioning` state. Returns the row id so the
     * caller (the SandboxTracker handle) can update the same row through the
     * rest of the sandbox's life.
     */
    async create(opts: { teamId: number; applicationId: string; revisionId: string }): Promise<SandboxInstanceRow> {
        const { rows } = await this.options.db.pool.query<{ id: string }>(
            `INSERT INTO agent_stack_agentapplicationsandboxinstance
                (id, team_id, application_id, revision_id,
                 modal_sandbox_id, state, error_message, created_at)
             VALUES (gen_random_uuid(), $1, $2, $3,
                 '', 'provisioning', '', NOW())
             RETURNING id::text`,
            [opts.teamId, opts.applicationId, opts.revisionId]
        )
        return { id: rows[0].id, state: 'provisioning' }
    }

    /** PROVISIONING → READY. Sets `modal_sandbox_id` to the provider's external id. */
    async markReady(id: string, providerSandboxId: string): Promise<void> {
        await this.options.db.pool.query(
            `UPDATE agent_stack_agentapplicationsandboxinstance
             SET state = 'ready', modal_sandbox_id = $2, last_used_at = NOW()
             WHERE id = $1`,
            [id, providerSandboxId]
        )
    }

    /**
     * Refresh `last_used_at` so the staleness-based reaper doesn't murder an
     * actively-used sandbox. Best-effort: callers should not block tool
     * dispatch on this query.
     */
    async touch(id: string): Promise<void> {
        await this.options.db.pool.query(
            `UPDATE agent_stack_agentapplicationsandboxinstance
             SET last_used_at = NOW()
             WHERE id = $1`,
            [id]
        )
    }

    /**
     * Acquire or invoke failed irrecoverably. Records the (truncated) error
     * and marks terminated so reapers skip over the row.
     */
    async markFailed(id: string, errorMessage: string): Promise<void> {
        await this.options.db.pool.query(
            `UPDATE agent_stack_agentapplicationsandboxinstance
             SET state = 'terminated', error_message = $2, terminated_at = NOW()
             WHERE id = $1`,
            [id, errorMessage.slice(0, 4000)]
        )
    }

    /** Clean release. READY → TERMINATED with `terminated_at = NOW()`. */
    async markTerminated(id: string): Promise<void> {
        await this.options.db.pool.query(
            `UPDATE agent_stack_agentapplicationsandboxinstance
             SET state = 'terminated', terminated_at = NOW()
             WHERE id = $1`,
            [id]
        )
    }

    /**
     * Find rows still claiming to be ready/provisioning whose `last_used_at`
     * (or `created_at` if never touched) is older than `maxAgeMs`. The janitor
     * uses this to reap sandboxes whose worker died mid-session.
     */
    async findStale(maxAgeMs: number, limit = 100): Promise<StaleSandboxRow[]> {
        const { rows } = await this.options.db.pool.query<{
            id: string
            state: SandboxState
            provider_sandbox_id: string
        }>(
            `SELECT id::text, state, modal_sandbox_id AS provider_sandbox_id
             FROM agent_stack_agentapplicationsandboxinstance
             WHERE state IN ('provisioning', 'ready', 'terminating')
               AND COALESCE(last_used_at, created_at) < NOW() - ($1 || ' milliseconds')::interval
             ORDER BY COALESCE(last_used_at, created_at) ASC
             LIMIT $2`,
            [String(maxAgeMs), limit]
        )
        return rows.map((r) => ({
            id: r.id,
            state: r.state,
            providerSandboxId: r.provider_sandbox_id,
            providerKind: inferProviderKind(r.provider_sandbox_id),
        }))
    }
}
