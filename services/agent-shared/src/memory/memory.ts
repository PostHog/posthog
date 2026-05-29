// Agent memory — the tool surface, team-scoped, per-pattern allowlist.
//
// Every method takes a Scope = { teamId, applicationId } — the identity the
// runner asserts for a session (§7). team_id is the hard tenancy wall; the
// per-pattern grant is the only access mechanism (§3). Recall ranking is
// delegated to an opaque Recaller (§5) — FTS today, embeddings later.

import type { Pool } from 'pg'

import type { Recaller, Candidate } from './recaller'

export interface Scope {
    teamId: number
    applicationId: string
}

export type Access = 'read' | 'write'
export interface FacetDef {
    name: string
    type: 'text'
}
export type Filter = { field: string; op: '=' | '!=' | '~' | '>' | '<'; value: string }

export interface MemoryResult<T = unknown> {
    ok: boolean
    error?: string
    data?: T
}

const NAME_RE = /^[a-z_][a-z0-9_-]*$/

export class Memory {
    constructor(
        private readonly pool: Pool,
        private readonly recaller: Recaller
    ) {}

    // === Access ===

    /** Effective access for an app on a pattern. write implies read. null = none. */
    private async grantFor(scope: Scope, pattern: string): Promise<Access | null> {
        const r = await this.pool.query(
            `SELECT access FROM agent_memory_pattern_grant
             WHERE team_id = $1 AND pattern = $2 AND application_id = $3`,
            [scope.teamId, pattern, scope.applicationId]
        )
        return (r.rows[0]?.access as Access) ?? null
    }

    private async canRead(scope: Scope, pattern: string): Promise<boolean> {
        return (await this.grantFor(scope, pattern)) !== null
    }

    private async canWrite(scope: Scope, pattern: string): Promise<boolean> {
        return (await this.grantFor(scope, pattern)) === 'write'
    }

    /** Patterns this app may read (write implies read), within its team. */
    private async readablePatterns(scope: Scope): Promise<string[]> {
        const r = await this.pool.query(
            `SELECT g.pattern FROM agent_memory_pattern_grant g
             JOIN agent_memory_pattern p ON p.team_id = g.team_id AND p.name = g.pattern
             WHERE g.team_id = $1 AND g.application_id = $2 AND p.archived_at IS NULL`,
            [scope.teamId, scope.applicationId]
        )
        return r.rows.map((row) => row.pattern as string)
    }

    // === Schema (memory-evolve) ===

    /** Create a pattern. Creator-only by default (a write grant for the caller). */
    async createPattern(
        scope: Scope,
        input: { name: string; doctrine?: string; facets: FacetDef[] }
    ): Promise<MemoryResult> {
        if (!NAME_RE.test(input.name)) {
            return err(`invalid pattern name "${input.name}"`)
        }
        if (!input.facets?.length) {
            return err('at least one facet is required')
        }
        for (const f of input.facets) {
            if (!NAME_RE.test(f.name)) {
                return err(`invalid facet name "${f.name}"`)
            }
        }
        const exists = await this.pool.query(`SELECT 1 FROM agent_memory_pattern WHERE team_id = $1 AND name = $2`, [
            scope.teamId,
            input.name,
        ])
        if (exists.rowCount) {
            return err(`pattern "${input.name}" already exists`)
        }

        await this.pool.query(
            `INSERT INTO agent_memory_pattern (team_id, name, doctrine, facets, created_by)
             VALUES ($1, $2, $3, $4::jsonb, $5)`,
            [scope.teamId, input.name, input.doctrine ?? '', JSON.stringify(input.facets), scope.applicationId]
        )
        await this.pool.query(
            `INSERT INTO agent_memory_pattern_grant (team_id, pattern, application_id, access)
             VALUES ($1, $2, $3, 'write')`,
            [scope.teamId, input.name, scope.applicationId]
        )
        return ok({ pattern: input.name, access: 'write' })
    }

    /**
     * Widen a pattern's allowlist to another agent. In production this is the
     * approval-gated step (§4): exposing one agent's memory to another should
     * require a team admin's sign-off. The slice enforces only that the caller
     * already has write on the pattern; the approval hook is a platform concern.
     */
    async grant(
        scope: Scope,
        input: { pattern: string; applicationId: string; access: Access }
    ): Promise<MemoryResult> {
        if (!(await this.canWrite(scope, input.pattern))) {
            return err(`no write access to "${input.pattern}"`)
        }
        await this.pool.query(
            `INSERT INTO agent_memory_pattern_grant (team_id, pattern, application_id, access)
             VALUES ($1, $2, $3, $4)
             ON CONFLICT (team_id, pattern, application_id) DO UPDATE SET access = EXCLUDED.access`,
            [scope.teamId, input.pattern, input.applicationId, input.access]
        )
        const shared = input.applicationId !== scope.applicationId
        return ok({
            pattern: input.pattern,
            granted: input.applicationId,
            access: input.access,
            requires_approval_in_prod: shared,
        })
    }

    // === Writes (memory-mutate) ===

    async create(scope: Scope, pattern: string, facets: Record<string, string>): Promise<MemoryResult> {
        if (!(await this.canWrite(scope, pattern))) {
            return err(`no write access to "${pattern}"`)
        }
        const r = await this.pool.query(
            `INSERT INTO agent_memory_entry (team_id, pattern, facets)
             VALUES ($1, $2, $3::jsonb) RETURNING id, facets, version, created_at`,
            [scope.teamId, pattern, JSON.stringify(facets)]
        )
        return ok({ pattern, ...r.rows[0], id: Number(r.rows[0].id) })
    }

    async update(
        scope: Scope,
        pattern: string,
        id: number,
        facets: Record<string, string>,
        expectedVersion?: number
    ): Promise<MemoryResult> {
        if (!(await this.canWrite(scope, pattern))) {
            return err(`no write access to "${pattern}"`)
        }
        const params: unknown[] = [JSON.stringify(facets), scope.teamId, pattern, id]
        let where = `team_id = $2 AND pattern = $3 AND id = $4 AND archived_at IS NULL`
        if (expectedVersion != null) {
            where += ` AND version = $5`
            params.push(expectedVersion)
        }
        const r = await this.pool.query(
            `UPDATE agent_memory_entry SET facets = facets || $1::jsonb, version = version + 1, updated_at = now()
             WHERE ${where} RETURNING id, facets, version`,
            params
        )
        if (r.rowCount === 0) {
            return err(
                expectedVersion != null
                    ? `version conflict on ${pattern}/${id} — re-read and retry`
                    : `entry ${pattern}/${id} not found`
            )
        }
        return ok({ pattern, ...r.rows[0], id: Number(r.rows[0].id) })
    }

    async archive(scope: Scope, pattern: string, id: number): Promise<MemoryResult> {
        if (!(await this.canWrite(scope, pattern))) {
            return err(`no write access to "${pattern}"`)
        }
        await this.pool.query(
            `UPDATE agent_memory_entry SET archived_at = now() WHERE team_id = $1 AND pattern = $2 AND id = $3 AND archived_at IS NULL`,
            [scope.teamId, pattern, id]
        )
        return ok({ pattern, id, archived: true })
    }

    async link(
        scope: Scope,
        source: { pattern: string; id: number },
        target: { pattern: string; id: number },
        label?: string
    ): Promise<MemoryResult> {
        if (!(await this.canWrite(scope, source.pattern))) {
            return err(`no write access to "${source.pattern}"`)
        }
        await this.pool.query(
            `INSERT INTO agent_memory_link (team_id, source_pattern, source_id, target_pattern, target_id, label)
             VALUES ($1, $2, $3, $4, $5, $6)`,
            [scope.teamId, source.pattern, source.id, target.pattern, target.id, label ?? null]
        )
        return ok({ source, target, label })
    }

    // === Reads (memory-query / search / resolve) ===

    async query(scope: Scope, pattern: string, filters: Filter[] = [], limit = 50): Promise<MemoryResult> {
        if (!(await this.canRead(scope, pattern))) {
            return err(`no read access to "${pattern}"`)
        }
        const params: unknown[] = [scope.teamId, pattern]
        let sql = `SELECT id, facets, version, created_at, updated_at FROM agent_memory_entry
                   WHERE team_id = $1 AND pattern = $2 AND archived_at IS NULL`
        for (const f of filters) {
            if (!NAME_RE.test(f.field)) {
                return err(`invalid filter field "${f.field}"`)
            }
            params.push(f.op === '~' ? `%${f.value}%` : f.value)
            const op = f.op === '~' ? 'ILIKE' : f.op
            sql += ` AND facets->>'${f.field}' ${op} $${params.length}`
        }
        params.push(Math.min(limit, 1000))
        sql += ` ORDER BY updated_at DESC LIMIT $${params.length}`
        const r = await this.pool.query(sql, params)
        return ok({ pattern, entries: r.rows.map((e) => ({ ...e, id: Number(e.id) })), count: r.rowCount })
    }

    /** Cross-pattern substring search over the agent's readable patterns. */
    async search(scope: Scope, term: string, limit = 20): Promise<MemoryResult> {
        const patterns = await this.readablePatterns(scope)
        if (patterns.length === 0) {
            return ok({ term, results: [], count: 0 })
        }
        const r = await this.pool.query(
            `SELECT id, pattern, facets FROM agent_memory_entry
             WHERE team_id = $1 AND pattern = ANY($2) AND archived_at IS NULL AND facets::text ILIKE $3
             ORDER BY updated_at DESC LIMIT $4`,
            [scope.teamId, patterns, `%${term}%`, Math.min(limit, 1000)]
        )
        return ok({ term, results: r.rows.map((e) => ({ ...e, id: Number(e.id) })), count: r.rowCount })
    }

    async resolve(scope: Scope, uri: string): Promise<MemoryResult> {
        const m = uri.match(/^memory:\/\/entry\/([a-z0-9_-]+)\/(\d+)$/i)
        if (!m) {
            return err(`unresolvable uri "${uri}" (expect memory://entry/{pattern}/{id})`)
        }
        const [, pattern, idStr] = m
        if (!(await this.canRead(scope, pattern))) {
            return err(`no read access to "${pattern}"`)
        }
        const r = await this.pool.query(
            `SELECT id, facets, version FROM agent_memory_entry WHERE team_id = $1 AND pattern = $2 AND id = $3 AND archived_at IS NULL`,
            [scope.teamId, pattern, Number(idStr)]
        )
        if (r.rowCount === 0) {
            return err(`entry ${pattern}/${idStr} not found`)
        }
        return ok({ pattern, ...r.rows[0], id: Number(r.rows[0].id) })
    }

    // === Recall (memory-prime) ===

    /**
     * Auto-associative recall. Gather candidates from the agent's readable
     * patterns, rank by the opaque Recaller, expand one hop along links.
     * Identical contract regardless of whether ranking is FTS or embeddings.
     */
    async prime(scope: Scope, cue: string, opts: { patterns?: string[]; limit?: number } = {}): Promise<MemoryResult> {
        const limit = opts.limit ?? 5
        let patterns = await this.readablePatterns(scope)
        if (opts.patterns?.length) {
            patterns = patterns.filter((p) => opts.patterns!.includes(p))
        }
        if (patterns.length === 0) {
            return ok({ cue, ranker: this.recaller.kind, results: [], count: 0 })
        }

        const rows = await this.pool.query(
            `SELECT id, pattern, facets FROM agent_memory_entry
             WHERE team_id = $1 AND pattern = ANY($2) AND archived_at IS NULL`,
            [scope.teamId, patterns]
        )
        const candidates: Candidate[] = rows.rows.map((row) => ({
            pattern: row.pattern as string,
            id: Number(row.id),
            text: buildText(row.pattern as string, row.facets as Record<string, unknown>),
            entry: row.facets as Record<string, unknown>,
        }))

        const ranked = await this.recaller.rank(cue, candidates, Math.min(limit * 3, 50))
        const top = ranked.slice(0, limit)

        const results = []
        for (const r of top) {
            const linked = await this.oneHop(scope, r.pattern, r.id)
            results.push({
                pattern: r.pattern,
                id: r.id,
                relevance: r.score,
                entry: r.entry,
                uri: `memory://entry/${r.pattern}/${r.id}`,
                ...(linked.length ? { linked } : {}),
            })
        }
        return ok({ cue, ranker: this.recaller.kind, results, count: results.length })
    }

    /** One-hop link expansion (bidirectional), filtered to readable patterns. */
    private async oneHop(scope: Scope, pattern: string, id: number): Promise<unknown[]> {
        const r = await this.pool.query(
            `SELECT target_pattern AS p, target_id AS i, label FROM agent_memory_link
               WHERE team_id = $1 AND source_pattern = $2 AND source_id = $3 AND archived_at IS NULL
             UNION ALL
             SELECT source_pattern AS p, source_id AS i, label FROM agent_memory_link
               WHERE team_id = $1 AND target_pattern = $2 AND target_id = $3 AND archived_at IS NULL`,
            [scope.teamId, pattern, id]
        )
        const out: unknown[] = []
        for (const row of r.rows) {
            if (!(await this.canRead(scope, row.p))) {
                continue
            }
            const e = await this.pool.query(
                `SELECT id, facets FROM agent_memory_entry WHERE team_id = $1 AND pattern = $2 AND id = $3 AND archived_at IS NULL`,
                [scope.teamId, row.p, row.i]
            )
            if (e.rowCount) {
                out.push({
                    pattern: row.p,
                    id: Number(row.i),
                    label: row.label ?? undefined,
                    entry: e.rows[0].facets,
                    uri: `memory://entry/${row.p}/${row.i}`,
                })
            }
        }
        return out
    }
}

function buildText(pattern: string, facets: Record<string, unknown>): string {
    const parts = [pattern]
    for (const v of Object.values(facets)) {
        if (typeof v === 'string' && v) {
            parts.push(v)
        }
    }
    return parts.join('. ')
}

function ok<T>(data: T): MemoryResult<T> {
    return { ok: true, data }
}
function err(error: string): MemoryResult {
    return { ok: false, error }
}
