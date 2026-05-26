import type { ResolvedIdentity } from '@repo/ass-server/types'

import { logger } from '../logger'
import { PosthogDbClient } from './client'

export interface IdentitiesRepositoryOptions {
    db: PosthogDbClient
}

export interface ResolvedAgentUser {
    spaceId: string
    userId: string
}

export class IdentitySpaceNotFoundError extends Error {
    constructor(
        public readonly teamId: number,
        public readonly spaceName: string
    ) {
        super(`identity space '${spaceName}' not found for team ${teamId}`)
        this.name = 'IdentitySpaceNotFoundError'
    }
}

/**
 * Find-or-create the AgentUser an asserted provider identity maps to,
 * inside the named identity space — Layer 3 of agent-stack/docs/auth-and-identity.md.
 *
 * Follows the same direct-Postgres pattern as `ApplicationsRepository`:
 * runtime services own the access pattern, no extra HTTP hop through Django.
 *
 * The find-or-create is split into two steps wrapped in a transaction so we
 * race-safely allocate at most one `AgentUser` per provider tuple. The
 * `UserIdentity` table has a unique constraint on
 * `(space, provider, provider_account_id, provider_subject)` — ON CONFLICT
 * does the heavy lifting. If two callers race, only one INSERT wins; the
 * loser reads the winner's row via the `RETURNING` clause.
 */
export class IdentitiesRepository {
    constructor(private readonly options: IdentitiesRepositoryOptions) {}

    /**
     * Resolve `(team, space-name, provider-tuple)` to a stable
     * `{spaceId, userId}`. Throws `IdentitySpaceNotFoundError` if the space
     * doesn't exist (a misconfigured agent — surfaced as a 500 by the
     * caller, not a 404 to the end-user).
     */
    async resolveIdentity(teamId: number, spaceName: string, identity: ResolvedIdentity): Promise<ResolvedAgentUser> {
        const client = await this.options.db.pool.connect()
        try {
            await client.query('BEGIN')

            // 1. Resolve the space id by (team, name). Soft-deleted spaces
            //    are invisible — the unique constraint already excludes them.
            const spaceRes = await client.query<{ id: string }>(
                `SELECT id::text AS id
                 FROM agent_stack_identityspace
                 WHERE team_id = $1 AND name = $2 AND deleted = FALSE
                 LIMIT 1`,
                [teamId, spaceName]
            )
            if (spaceRes.rows.length === 0) {
                await client.query('ROLLBACK')
                throw new IdentitySpaceNotFoundError(teamId, spaceName)
            }
            const spaceId = spaceRes.rows[0].id

            // 2. Find-or-create the user behind this identity tuple.
            //    The pattern: optimistically INSERT a new AgentUser + the
            //    UserIdentity that points at it. The UserIdentity has a
            //    UNIQUE constraint on (space, provider, account, subject) —
            //    on conflict we read the existing row's user_id and discard
            //    our just-inserted-but-orphaned AgentUser.
            //
            //    Cleaner alternative would be a single CTE, but the
            //    two-statement form is easier to read and the orphan window
            //    is bounded by the transaction.

            // Pre-mint a uuid so we can reference it across both INSERTs.
            // The Django `UUIDModel.default=uuid7` only fires via the ORM —
            // raw SQL inserts must supply the id explicitly. `gen_random_uuid()`
            // (v4) is fine here; nothing in the schema depends on uuid7's
            // time-ordering for AgentUser rows.
            const newUserRes = await client.query<{ id: string }>(
                `INSERT INTO agent_stack_agentuser (id, space_id, created_at, last_seen_at)
                 VALUES (gen_random_uuid(), $1, NOW(), NOW())
                 RETURNING id::text AS id`,
                [spaceId]
            )
            const candidateUserId = newUserRes.rows[0].id

            const identityRes = await client.query<{ user_id: string }>(
                `INSERT INTO agent_stack_useridentity
                     (id, space_id, user_id, provider, provider_account_id, provider_subject, created_at)
                 VALUES (gen_random_uuid(), $1, $2, $3, $4, $5, NOW())
                 ON CONFLICT (space_id, provider, provider_account_id, provider_subject)
                 DO UPDATE SET created_at = agent_stack_useridentity.created_at
                 RETURNING user_id::text AS user_id`,
                [spaceId, candidateUserId, identity.provider, identity.providerAccountId, identity.providerSubject]
            )
            const userId = identityRes.rows[0].user_id

            if (userId !== candidateUserId) {
                // Lost the race / the tuple already existed — drop the
                // orphaned AgentUser we created above. Touch last_seen on
                // the real one so we have a freshness signal for telemetry.
                await client.query(`DELETE FROM agent_stack_agentuser WHERE id = $1`, [candidateUserId])
                await client.query(`UPDATE agent_stack_agentuser SET last_seen_at = NOW() WHERE id = $1`, [userId])
            }

            await client.query('COMMIT')
            return { spaceId, userId }
        } catch (err) {
            try {
                await client.query('ROLLBACK')
            } catch {
                // Already rolled back; nothing to do.
            }
            if (err instanceof IdentitySpaceNotFoundError) {
                throw err
            }
            logger.error('resolveIdentity failed', {
                error: String(err),
                teamId,
                spaceName,
                provider: identity.provider,
            })
            throw err
        } finally {
            client.release()
        }
    }
}
