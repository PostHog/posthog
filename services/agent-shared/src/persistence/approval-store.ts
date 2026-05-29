/**
 * Approval-gated tool requests — interface + in-memory test impl.
 *
 * See docs/agent-platform/plans/approval-gated-tools.md for the design.
 *
 * The dispatcher writes a row when an approval-gated tool call is intercepted.
 * Sessions do NOT park — the model receives a synthetic queued tool_result
 * containing an approval link. The approval API later marks the row
 * `approving` → `dispatched` (running the real tool platform-side) and
 * injects the result back into the session.
 *
 * Idempotency: a new row for the same `(session_id, tool_name, args_hash)`
 * with `state='queued'` returns the existing row instead of inserting a
 * duplicate. After a terminal state (rejected / expired / dispatched*) the
 * model can re-issue the call and the dispatcher creates a fresh row.
 */

import { createHash } from 'node:crypto'

import { AssistantMessageRecord } from '../spec/spec'

export type ApprovalRequestState = 'queued' | 'approving' | 'dispatched' | 'dispatched_failed' | 'rejected' | 'expired'

export interface ApprovalRequest {
    id: string
    session_id: string
    application_id: string
    team_id: number
    revision_id: string
    turn: number
    tool_call_id: string
    tool_name: string
    proposed_args: Record<string, unknown>
    args_hash: Buffer
    /** Snapshot of the assistant message that emitted the call. */
    assistant_message: AssistantMessageRecord
    /** Resolved approver policy at request time — v0 always `["team_admins"]`. */
    approver_scope: { approvers: string[]; allow_edit: boolean; allow_agent_approver: boolean }
    state: ApprovalRequestState
    decision_by: string | null
    decision_at: string | null
    decision_reason: string | null
    decided_args: Record<string, unknown> | null
    /** Set on terminal decision. `{result?, error?}`. */
    dispatch_outcome: { result?: unknown; error?: string } | null
    created_at: string
    expires_at: string
}

export interface UpsertApprovalRequestInput {
    id: string
    session_id: string
    application_id: string
    team_id: number
    revision_id: string
    turn: number
    tool_call_id: string
    tool_name: string
    proposed_args: Record<string, unknown>
    assistant_message: AssistantMessageRecord
    approver_scope: ApprovalRequest['approver_scope']
    expires_at: string
}

export interface UpsertApprovalRequestResult {
    request: ApprovalRequest
    /** True when an existing queued row was returned instead of inserting a new one. */
    deduped: boolean
}

export interface DecideApprovalInput {
    decided_by: string
    decided_at: string
    /** Approver's free-form reason, surfaces in the synthetic tool_result. */
    reason?: string
    /** Approver-edited args. Caller must validate `allow_edit` in spec policy. */
    decided_args?: Record<string, unknown>
}

export interface ListApprovalsOpts {
    state?: ApprovalRequestState | ApprovalRequestState[]
    limit?: number
    offset?: number
}

export interface ApprovalStore {
    /**
     * UPSERT by (session_id, tool_name, args_hash) WHERE state='queued'.
     * Returns the existing queued row if one exists, else inserts the new row.
     */
    upsertQueued(input: UpsertApprovalRequestInput): Promise<UpsertApprovalRequestResult>
    get(id: string): Promise<ApprovalRequest | null>
    /** Returns the most recently created request for a (session, tool, args). */
    findLatestByArgs(sessionId: string, toolName: string, argsHash: Buffer): Promise<ApprovalRequest | null>
    /** Atomically flip `queued` → `approving` with stamp. Returns null when not in `queued`. */
    markApproving(id: string, input: DecideApprovalInput): Promise<ApprovalRequest | null>
    /** Final state after the platform ran the tool. */
    markDispatched(id: string, outcome: { result?: unknown; error?: string }): Promise<ApprovalRequest | null>
    markRejected(id: string, input: DecideApprovalInput): Promise<ApprovalRequest | null>
    /** Janitor sweep — flips `queued` rows past `expires_at` to `expired`. Returns rows that flipped. */
    expireQueued(now: string): Promise<ApprovalRequest[]>
    /** UI / inbox listings. team_id and application_id are denormalised for these. */
    listByTeam(teamId: number, opts?: ListApprovalsOpts): Promise<ApprovalRequest[]>
    listByApplication(applicationId: string, opts?: ListApprovalsOpts): Promise<ApprovalRequest[]>
    listBySession(sessionId: string, opts?: ListApprovalsOpts): Promise<ApprovalRequest[]>
}

/**
 * Canonicalise a JSON-serialisable args object so semantically identical
 * args produce the same SHA-256. Recursive key sort + JSON.stringify + sha256.
 *
 * Numbers / booleans / strings / arrays / null pass through unchanged.
 * Floats vs ints (`1` vs `1.0`) are NOT normalised — see plan §5.1.
 */
export function hashCanonicalArgs(args: unknown): Buffer {
    const canonical = JSON.stringify(sortKeys(args))
    return createHash('sha256').update(canonical, 'utf8').digest()
}

function sortKeys(value: unknown): unknown {
    if (Array.isArray(value)) {
        return value.map(sortKeys)
    }
    if (value && typeof value === 'object') {
        const out: Record<string, unknown> = {}
        for (const k of Object.keys(value as Record<string, unknown>).sort()) {
            out[k] = sortKeys((value as Record<string, unknown>)[k])
        }
        return out
    }
    return value
}

/** In-memory test impl. Not thread-safe across processes. */
export class MemoryApprovalStore implements ApprovalStore {
    private readonly rows = new Map<string, ApprovalRequest>()

    async upsertQueued(input: UpsertApprovalRequestInput): Promise<UpsertApprovalRequestResult> {
        const argsHash = hashCanonicalArgs(input.proposed_args)
        for (const r of this.rows.values()) {
            if (
                r.session_id === input.session_id &&
                r.tool_name === input.tool_name &&
                r.args_hash.equals(argsHash) &&
                r.state === 'queued'
            ) {
                return { request: r, deduped: true }
            }
        }
        const now = new Date().toISOString()
        const req: ApprovalRequest = {
            id: input.id,
            session_id: input.session_id,
            application_id: input.application_id,
            team_id: input.team_id,
            revision_id: input.revision_id,
            turn: input.turn,
            tool_call_id: input.tool_call_id,
            tool_name: input.tool_name,
            proposed_args: input.proposed_args,
            args_hash: argsHash,
            assistant_message: input.assistant_message,
            approver_scope: input.approver_scope,
            state: 'queued',
            decision_by: null,
            decision_at: null,
            decision_reason: null,
            decided_args: null,
            dispatch_outcome: null,
            created_at: now,
            expires_at: input.expires_at,
        }
        this.rows.set(req.id, req)
        return { request: req, deduped: false }
    }

    async get(id: string): Promise<ApprovalRequest | null> {
        return this.rows.get(id) ?? null
    }

    async findLatestByArgs(sessionId: string, toolName: string, argsHash: Buffer): Promise<ApprovalRequest | null> {
        const matches = [...this.rows.values()]
            .filter((r) => r.session_id === sessionId && r.tool_name === toolName && r.args_hash.equals(argsHash))
            .sort(byCreatedAtDesc)
        return matches[0] ?? null
    }

    async markApproving(id: string, input: DecideApprovalInput): Promise<ApprovalRequest | null> {
        const r = this.rows.get(id)
        if (!r || r.state !== 'queued') {
            return null
        }
        r.state = 'approving'
        r.decision_by = input.decided_by
        r.decision_at = input.decided_at
        r.decision_reason = input.reason ?? null
        r.decided_args = input.decided_args ?? null
        return r
    }

    async markDispatched(id: string, outcome: { result?: unknown; error?: string }): Promise<ApprovalRequest | null> {
        const r = this.rows.get(id)
        if (!r || r.state !== 'approving') {
            return null
        }
        r.dispatch_outcome = outcome
        r.state = outcome.error ? 'dispatched_failed' : 'dispatched'
        return r
    }

    async markRejected(id: string, input: DecideApprovalInput): Promise<ApprovalRequest | null> {
        const r = this.rows.get(id)
        if (!r || r.state !== 'queued') {
            return null
        }
        r.state = 'rejected'
        r.decision_by = input.decided_by
        r.decision_at = input.decided_at
        r.decision_reason = input.reason ?? null
        return r
    }

    async expireQueued(now: string): Promise<ApprovalRequest[]> {
        const out: ApprovalRequest[] = []
        for (const r of this.rows.values()) {
            if (r.state === 'queued' && r.expires_at <= now) {
                r.state = 'expired'
                out.push(r)
            }
        }
        return out
    }

    async listByTeam(teamId: number, opts: ListApprovalsOpts = {}): Promise<ApprovalRequest[]> {
        return this.list((r) => r.team_id === teamId, opts)
    }

    async listByApplication(applicationId: string, opts: ListApprovalsOpts = {}): Promise<ApprovalRequest[]> {
        return this.list((r) => r.application_id === applicationId, opts)
    }

    async listBySession(sessionId: string, opts: ListApprovalsOpts = {}): Promise<ApprovalRequest[]> {
        return this.list((r) => r.session_id === sessionId, opts)
    }

    private list(predicate: (r: ApprovalRequest) => boolean, opts: ListApprovalsOpts): ApprovalRequest[] {
        const stateSet = normaliseStates(opts.state)
        const limit = opts.limit ?? 100
        const offset = opts.offset ?? 0
        const matches = [...this.rows.values()]
            .filter((r) => predicate(r) && (!stateSet || stateSet.has(r.state)))
            .sort(byCreatedAtDesc)
        return matches.slice(offset, offset + limit)
    }
}

// Tests insert rows within the same millisecond — keep ordering deterministic
// by falling back to the insertion order via id when timestamps tie.
function byCreatedAtDesc(a: ApprovalRequest, b: ApprovalRequest): number {
    return b.created_at.localeCompare(a.created_at) || b.id.localeCompare(a.id)
}

function normaliseStates(s: ListApprovalsOpts['state']): Set<ApprovalRequestState> | null {
    if (!s) {
        return null
    }
    return new Set(Array.isArray(s) ? s : [s])
}
