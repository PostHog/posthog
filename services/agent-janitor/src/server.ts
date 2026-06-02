/**
 * Internal HTTP for Django. The janitor doubles as the agent-admin surface
 * because (a) it already runs as a deploy unit, (b) it already has DB +
 * bundle store access, (c) auth is one shared internal secret.
 *
 * Endpoints (grouped):
 *
 *   Session lifecycle (existing):
 *     GET    /sessions?application_id=  list sessions for one application (newest first)
 *     GET    /sessions/:id              full session state
 *     POST   /sessions/:id/cancel       mark failed
 *     POST   /sweep                     trigger a sweep (tests / debug)
 *
 *   Bundle authoring (proxied by the Django API):
 *     GET    /revisions/:id/manifest    list paths + sizes + sha256
 *     GET    /revisions/:id/file        ?path=...  read one file
 *     PUT    /revisions/:id/file        ?path=...  write one file (draft)
 *     DELETE /revisions/:id/file        ?path=...  delete one file (draft)
 *     GET    /revisions/:id/bundle      bulk pull {files: {path: text}}
 *     PUT    /revisions/:id/bundle      bulk push {files, mode: replace|merge}
 *     POST   /revisions/:id/freeze      draft → frozen, returns sha256
 *     POST   /revisions/:id/validate    pre-flight checks (entrypoint, tool ids, custom-tool files, skill paths)
 *     POST   /revisions/:id/clone_from  {source_revision_id, target_revision_id}
 *
 *   Catalog (proxied by Django):
 *     GET    /native_tools              every @posthog/* tool the runner knows
 *
 *   Health:
 *     GET    /healthz
 *
 * Auth: a single shared-secret header (`x-internal-secret`). Django keeps the
 * team / scope checks on its side; this layer trusts the request once the
 * secret matches.
 *
 * Defensive shape: every async route is wrapped in `asyncHandler` so a
 * rejected promise lands in the global `errorHandler` below instead of
 * becoming an `unhandledRejection`. Bodies + query params are validated
 * with zod at the edge — invalid input returns a structured 400, never a
 * 500 / process crash. See [http-utils.ts](./http-utils.ts).
 */

import express, { Express, NextFunction, Request, Response } from 'express'
import { randomUUID } from 'node:crypto'
import { z } from 'zod'

import {
    accumulateUsage,
    AgentSession,
    ApprovalRequest,
    ApprovalStore,
    BundleStore,
    buildSystemPrompt,
    ConversationMessage,
    createLogger,
    EMPTY_USAGE_TOTAL,
    FRAMEWORK_PROMPT_VERSION,
    lastAssistantTextPreview,
    MemoryStore,
    RevisionStore,
    SessionQueue,
} from '@posthog/agent-shared'
import { listNativeTools } from '@posthog/agent-tools'

import { mountMemoryRoutes } from './api/memory'
import { buildApprovalDecidedMarker } from './approval-marker'
import { fireCronManually } from './cron-tick'
import { asyncHandler, errorHandler } from './http-utils'
import { SweepDeps, sweepOnce } from './sweep'
import { validateRevisionBundle } from './validate-spec'

const log = createLogger('agent-janitor.server')

export interface JanitorServerOpts {
    queue: SessionQueue
    sweep: SweepDeps
    /** Required for the /revisions/* + /native_tools endpoints. */
    revisions?: RevisionStore
    bundles?: BundleStore
    /**
     * Required for the /approvals/* endpoints. When omitted, those routes
     * return 503 so a misconfigured janitor surfaces the gap loudly
     * rather than silently dropping decisions on the floor.
     */
    approvals?: ApprovalStore
    /**
     * S3-backed memory store. Required for the /memory/* endpoints. When
     * omitted those routes return 503 — same convention as `approvals`.
     * Wired from `AGENT_MEMORY_S3_*` in index.ts; tests substitute an
     * `InMemoryMemoryStore` directly.
     */
    memoryStore?: MemoryStore
    internalSecret?: string
}

const SessionStateSchema = z.enum(['queued', 'running', 'completed', 'closed', 'failed'])

const ListSessionsQuerySchema = z.object({
    application_id: z.string().min(1, 'missing_application_id'),
    limit: z.coerce.number().int().positive().max(1000).optional(),
    offset: z.coerce.number().int().nonnegative().optional(),
    // `state` can be ?state=completed or ?state=completed,failed
    state: z
        .string()
        .optional()
        .transform((s) => (s ? s.split(',').filter(Boolean) : undefined))
        .pipe(z.array(SessionStateSchema).optional()),
    revision_id: z.string().optional(),
    created_after: z.string().optional(),
    created_before: z.string().optional(),
})

const GetSessionQuerySchema = z.object({
    last_n: z.coerce.number().int().nonnegative().optional(),
})

const AggregateForApplicationQuerySchema = z.object({
    application_id: z.string().min(1, 'missing_application_id'),
    /** ISO timestamp — defaults to 24h ago. */
    since: z.string().optional(),
})

const AggregateForTeamQuerySchema = z.object({
    team_id: z.coerce.number().int().positive('missing_team_id'),
    since: z.string().optional(),
})

const ListLiveForTeamQuerySchema = z.object({
    team_id: z.coerce.number().int().positive('missing_team_id'),
    limit: z.coerce.number().int().positive().max(500).optional(),
})

function defaultSince(): string {
    return new Date(Date.now() - 24 * 60 * 60 * 1000).toISOString()
}

const BackfillUsageBodySchema = z.object({
    /**
     * Walk sessions for this application. Required so a single call can't
     * scan every session in the cluster — call repeatedly per app.
     */
    application_id: z.string().min(1, 'missing_application_id'),
    /** Count what would change without writing. Default true to keep accidents cheap. */
    dry_run: z.boolean().default(true),
    /** Cap on rows scanned per call so a giant backlog doesn't tie up the request. */
    limit: z.coerce.number().int().positive().max(5000).default(500),
})

const FilePathQuerySchema = z.object({
    path: z.string().min(1, 'missing_path'),
})

// Per-file ceiling, well below the express.json() 8MB limit. The 8MB cap
// lets a single ~7MB file path slip through; this stops that. Bundles
// containing files larger than this should land via S3 presigned URLs
// (future work — see typed-config-loader.md notes).
const MAX_FILE_BYTES = 1_000_000 // 1 MB per file
// Per-bundle ceiling — sum of all file content. Defends against a bulk
// push with many under-limit files that still exhausts disk / memory.
const MAX_BUNDLE_BYTES = 4_000_000 // 4 MB across all files in one push

function utf8Bytes(s: string): number {
    return Buffer.byteLength(s, 'utf8')
}

const FileUpdateBodySchema = z.object({
    content: z
        .string()
        .refine((s) => utf8Bytes(s) <= MAX_FILE_BYTES, { message: `file content exceeds ${MAX_FILE_BYTES} bytes` }),
})

const CronFireBodySchema = z.object({
    /** Cron `name` from `spec.triggers[].config.name`. */
    cron_name: z.string().min(1),
    /**
     * Optional client-supplied id so repeated clicks of the same UI "fire
     * now" button dedupe. Without it, every call generates a fresh UUID and
     * fires unconditionally. Stripe-shaped — same convention the
     * Idempotency-Key header uses on the webhook trigger.
     */
    request_id: z.string().min(1).optional(),
    /**
     * Override the firing timestamp. Defaults to "now." Lets the authoring
     * UI replay a historical firing for debugging — placeholder expansion
     * resolves against this timestamp.
     */
    fired_at: z.string().datetime({ offset: true }).optional(),
})

const BundleFilesSchema = z.record(z.string(), z.string()).superRefine((files, ctx) => {
    let total = 0
    for (const [path, content] of Object.entries(files)) {
        const bytes = utf8Bytes(content)
        if (bytes > MAX_FILE_BYTES) {
            ctx.addIssue({
                code: 'custom',
                path: [path],
                message: `file content exceeds ${MAX_FILE_BYTES} bytes`,
            })
        }
        total += bytes
    }
    if (total > MAX_BUNDLE_BYTES) {
        ctx.addIssue({
            code: 'custom',
            message: `bundle total exceeds ${MAX_BUNDLE_BYTES} bytes`,
        })
    }
})
const BundlePutBodySchema = z.object({
    files: BundleFilesSchema,
    mode: z.enum(['replace', 'merge']).default('replace'),
})

const CloneFromBodySchema = z.object({
    source_revision_id: z.string().min(1, 'missing_source_revision_id'),
})

const ApprovalStateSchema = z.enum(['queued', 'approving', 'dispatched', 'dispatched_failed', 'rejected', 'expired'])

const ListApprovalsQuerySchema = z.object({
    application_id: z.string().min(1, 'missing_application_id'),
    state: z
        .string()
        .optional()
        .transform((s) => (s ? s.split(',').filter(Boolean) : undefined))
        .pipe(z.array(ApprovalStateSchema).optional()),
    limit: z.coerce.number().int().positive().max(500).optional(),
    offset: z.coerce.number().int().nonnegative().optional(),
})

const DecideApprovalBodySchema = z.object({
    decision: z.enum(['approve', 'reject']),
    decided_by: z.string().min(1, 'missing_decided_by'),
    /** Approver-edited args. Only honoured when spec.approval_policy.allow_edit is true. */
    edited_args: z.record(z.string(), z.unknown()).optional(),
    reason: z.string().optional(),
})

export function buildJanitorApp(opts: JanitorServerOpts): Express {
    const app = express()
    // JSON bodies up to 8MB cover any reasonable bundle bulk-push (TS source +
    // a few markdown files). Larger bundles should land an S3 presigned URL
    // path eventually; flagged in the bundle-push action below.
    app.use(express.json({ limit: '8mb' }))
    if (opts.internalSecret) {
        app.use((req: Request, res: Response, next: NextFunction) => {
            if (req.path === '/healthz') {
                next()
                return
            }
            const auth = req.headers['x-internal-secret']
            if (auth !== opts.internalSecret) {
                res.status(401).json({ error: 'unauthorized' })
                return
            }
            next()
        })
    }
    app.get('/healthz', (_req, res) => {
        res.json({ ok: true })
    })

    /* ───────────────────────────── sessions ───────────────────────────── */

    app.get(
        '/sessions',
        asyncHandler(async (req, res) => {
            const q = ListSessionsQuerySchema.parse(req.query)
            const filter = {
                states: q.state as AgentSession['state'][] | undefined,
                revisionId: q.revision_id,
                createdAfter: q.created_after,
                createdBefore: q.created_before,
            }
            const [sessions, count] = await Promise.all([
                opts.queue.listByApplication(q.application_id, { ...filter, limit: q.limit, offset: q.offset }),
                opts.queue.countByApplication(q.application_id, filter),
            ])
            // Conversation can be large; strip it from the list view but derive a
            // preview so a single tool call still tells you what the agent said.
            // usage_total reads off the persisted column — no JSONB walk.
            const summaries = sessions.map((s) => ({
                id: s.id,
                application_id: s.application_id,
                revision_id: s.revision_id,
                state: s.state,
                external_key: s.external_key,
                idempotency_key: s.idempotency_key,
                trigger_metadata: s.trigger_metadata,
                principal: s.principal,
                turns: s.conversation.length,
                preview: lastAssistantTextPreview(s.conversation),
                usage_total: s.usage_total,
                retry_count: s.retry_count,
                created_at: s.created_at,
                updated_at: s.updated_at,
            }))
            res.json({ results: summaries, count })
        })
    )

    /* ─────────────────────────── fleet stats ─────────────────────────── */
    //
    // Rollups that power the agent-console overview tiles. Kept on the
    // janitor (rather than agent-ingress) because (a) Django already
    // proxies through here for read-only authoring data, (b) these are
    // not in the hot per-request path so SELECT-on-jsonb is fine.
    //
    // Registered ahead of `/sessions/:id` — Express matches in order and
    // these literal paths would otherwise be swallowed by the `:id` param.

    app.get(
        '/sessions/stats',
        asyncHandler(async (req, res) => {
            const q = AggregateForApplicationQuerySchema.parse(req.query)
            const stats = await opts.queue.aggregateForApplication(q.application_id, q.since ?? defaultSince())
            res.json(stats)
        })
    )

    app.get(
        '/fleet/stats',
        asyncHandler(async (req, res) => {
            const q = AggregateForTeamQuerySchema.parse(req.query)
            const stats = await opts.queue.aggregateForTeam(q.team_id, q.since ?? defaultSince())
            res.json(stats)
        })
    )

    app.get(
        '/sessions/live',
        asyncHandler(async (req, res) => {
            const q = ListLiveForTeamQuerySchema.parse(req.query)
            const sessions = await opts.queue.listLiveForTeam(q.team_id, { limit: q.limit })
            const summaries = sessions.map((s) => ({
                id: s.id,
                application_id: s.application_id,
                revision_id: s.revision_id,
                team_id: s.team_id,
                state: s.state,
                external_key: s.external_key,
                principal: s.principal,
                turns: s.conversation.length,
                preview: lastAssistantTextPreview(s.conversation),
                usage_total: s.usage_total,
                created_at: s.created_at,
                updated_at: s.updated_at,
            }))
            res.json({ results: summaries })
        })
    )

    app.get(
        '/sessions/:id',
        asyncHandler(async (req, res) => {
            const q = GetSessionQuerySchema.parse(req.query)
            const s = await opts.queue.get(req.params.id)
            if (!s) {
                res.status(404).json({ error: 'not_found' })
                return
            }
            // Optional ?last_n=<int> returns just the tail of the conversation —
            // useful for huge sessions where the caller only cares about the most
            // recent turns. usage_total comes off the row regardless so cost
            // reporting stays accurate.
            if (q.last_n !== undefined && q.last_n < s.conversation.length) {
                const trimmed: AgentSession = {
                    ...s,
                    conversation: s.conversation.slice(-q.last_n),
                }
                res.json({
                    ...trimmed,
                    conversation_total_turns: s.conversation.length,
                    conversation_trimmed: true,
                })
                return
            }
            res.json({ ...s, conversation_trimmed: false })
        })
    )
    app.post(
        '/sessions/:id/cancel',
        asyncHandler(async (req, res) => {
            const s = await opts.queue.get(req.params.id)
            if (!s) {
                res.status(404).json({ error: 'not_found' })
                return
            }
            // Cancel is idempotent on terminal states — mirrors the chat
            // `/cancel` semantics.
            if (s.state === 'closed' || s.state === 'failed' || s.state === 'cancelled') {
                res.json({ ok: true, idempotent: true, state: s.state })
                return
            }
            await opts.queue.update(req.params.id, { state: 'cancelled' })
            res.json({ ok: true, state: 'cancelled' })
        })
    )
    app.post(
        '/sweep',
        asyncHandler(async (_req, res) => {
            const result = await sweepOnce(opts.sweep)
            res.json(result)
        })
    )

    // Recompute `usage_total` from `conversation` for sessions created before
    // the column existed (or where a backwards-compat write zeroed it). Plan:
    // docs/agent-platform/plans/per-turn-cost-capture.md §4.
    app.post(
        '/sessions/backfill_usage',
        asyncHandler(async (req, res) => {
            const body = BackfillUsageBodySchema.parse(req.body)
            const sessions = await opts.queue.listByApplication(body.application_id, { limit: body.limit })
            let scanned = 0
            let updated = 0
            for (const s of sessions) {
                scanned++
                const recomputed = s.conversation.reduce((acc, msg) => {
                    if (msg.role !== 'assistant' || !msg.usage) {
                        return acc
                    }
                    return accumulateUsage(acc, msg)
                }, EMPTY_USAGE_TOTAL)
                if (usageMatches(s.usage_total, recomputed)) {
                    continue
                }
                updated++
                if (!body.dry_run) {
                    await opts.queue.update(s.id, { usage_total: recomputed })
                }
            }
            res.json({ scanned, updated, dry_run: body.dry_run })
        })
    )

    /* ───────────────────────────── approvals ───────────────────────────── */
    //
    // Approval-gated tools — see docs/agent-platform/plans/approval-gated-tools.md.
    //
    // Django proxies through here for the list / show / decide surface so
    // the runtime DB (`agent_tool_approval_request`) stays node-owned, the
    // same way bundle CRUD goes via /revisions/*. The decide endpoint also
    // owns the wake path: mark the row, write the wake marker into
    // pending_inputs, flip session state back to `queued` so the runner
    // picks it up. For reject / no-edit-approve the synthetic tool_result
    // is materialised here too; for approve the runner dispatches the
    // tool on its next turn (so sandbox / secrets / integrations stay in
    // their existing home — see plan §B in the design doc).

    const needApprovalStore = (res: Response): boolean => {
        if (!opts.approvals) {
            res.status(503).json({ error: 'approval_store_not_configured' })
            return false
        }
        return true
    }

    const summariseApproval = (r: ApprovalRequest): Record<string, unknown> => ({
        id: r.id,
        session_id: r.session_id,
        application_id: r.application_id,
        team_id: r.team_id,
        revision_id: r.revision_id,
        turn: r.turn,
        tool_call_id: r.tool_call_id,
        tool_name: r.tool_name,
        proposed_args: r.proposed_args,
        decided_args: r.decided_args,
        assistant_message: r.assistant_message,
        approver_scope: r.approver_scope,
        state: r.state,
        decision_by: r.decision_by,
        decision_at: r.decision_at,
        decision_reason: r.decision_reason,
        dispatch_outcome: r.dispatch_outcome,
        created_at: r.created_at,
        expires_at: r.expires_at,
    })

    app.get(
        '/approvals',
        asyncHandler(async (req, res) => {
            if (!needApprovalStore(res)) {
                return
            }
            const q = ListApprovalsQuerySchema.parse(req.query)
            const rows = await opts.approvals!.listByApplication(q.application_id, {
                state: q.state,
                limit: q.limit,
                offset: q.offset,
            })
            res.json({ results: rows.map(summariseApproval) })
        })
    )

    app.get(
        '/approvals/:id',
        asyncHandler(async (req, res) => {
            if (!needApprovalStore(res)) {
                return
            }
            const row = await opts.approvals!.get(req.params.id)
            if (!row) {
                res.status(404).json({ error: 'not_found' })
                return
            }
            res.json(summariseApproval(row))
        })
    )

    app.post(
        '/approvals/:id/decide',
        asyncHandler(async (req, res) => {
            if (!needApprovalStore(res)) {
                return
            }
            const body = DecideApprovalBodySchema.parse(req.body)
            const existing = await opts.approvals!.get(req.params.id)
            if (!existing) {
                res.status(404).json({ error: 'not_found' })
                return
            }
            if (existing.state !== 'queued') {
                res.status(409).json({ error: 'not_queued', state: existing.state })
                return
            }

            // edited_args is only honoured when spec opted in. We surface
            // a structured 422 so Django can map to a user-facing error
            // rather than silently dropping the edits.
            if (body.edited_args !== undefined && !existing.approver_scope.allow_edit) {
                res.status(422).json({ error: 'edits_not_allowed' })
                return
            }

            const decidedAt = new Date().toISOString()
            if (body.decision === 'approve') {
                const updated = await opts.approvals!.markApproving(req.params.id, {
                    decided_by: body.decided_by,
                    decided_at: decidedAt,
                    reason: body.reason,
                    decided_args: body.edited_args,
                })
                if (!updated) {
                    // Lost the race to another decider.
                    res.status(409).json({ error: 'race_lost' })
                    return
                }
                // Wake the session. The runner picks up the marker on its
                // next turn, dispatches the tool, finalises the row, and
                // pushes the synthetic approved tool_result into the
                // conversation. See run-turn.ts marker-processing block.
                const wake: ConversationMessage = {
                    role: 'user',
                    content: [{ type: 'text', text: buildApprovalDecidedMarker(updated.id) }],
                    timestamp: Date.now(),
                }
                await opts.queue.appendPendingInput(existing.session_id, wake)
                await opts.queue.update(existing.session_id, { state: 'queued' })
                res.json({ ok: true, state: updated.state })
                return
            }

            // reject: terminal-here. Materialise the synthetic rejection
            // straight into pending_inputs as a `user` message — see the
            // note in run-turn's marker processor for why this isn't a
            // toolResult (Anthropic 400s when a tool_result follows a
            // closing assistant message instead of its matching tool_use).
            const updated = await opts.approvals!.markRejected(req.params.id, {
                decided_by: body.decided_by,
                decided_at: decidedAt,
                reason: body.reason,
            })
            if (!updated) {
                res.status(409).json({ error: 'race_lost' })
                return
            }
            const rejectedResult: ConversationMessage = {
                role: 'user',
                content: [
                    {
                        type: 'text',
                        text: JSON.stringify({
                            approval: {
                                request_id: updated.id,
                                state: 'rejected',
                                decided_by: updated.decision_by ?? undefined,
                                reason: updated.decision_reason ?? undefined,
                            },
                        }),
                    },
                ],
                timestamp: Date.now(),
            }
            await opts.queue.appendPendingInput(existing.session_id, rejectedResult)
            await opts.queue.update(existing.session_id, { state: 'queued' })
            res.json({ ok: true, state: updated.state })
        })
    )

    /* ───────────────────────────── catalog ───────────────────────────── */

    // Catalog of every @posthog/* native tool the runner knows about. The MCP
    // shows this to authoring models so they can pick tools to put in
    // spec.tools without guessing ids. Cached at module load — no DB call.
    app.get('/native_tools', (_req, res) => {
        res.json({ tools: listNativeTools() })
    })

    /* ───────────────────────────── revisions ───────────────────────────── */

    const needRevisionStore = (res: Response): boolean => {
        if (!opts.revisions || !opts.bundles) {
            res.status(503).json({ error: 'revision_store_not_configured' })
            return false
        }
        return true
    }

    const requireDraft = async (
        res: Response,
        revisionId: string
    ): Promise<{ rev: Awaited<ReturnType<RevisionStore['getRevision']>> } | null> => {
        const rev = await opts.revisions!.getRevision(revisionId)
        if (!rev) {
            res.status(404).json({ error: 'revision_not_found' })
            return null
        }
        if (rev.state !== 'draft') {
            res.status(409).json({ error: 'revision_not_editable', state: rev.state })
            return null
        }
        return { rev }
    }

    app.get(
        '/revisions/:id/manifest',
        asyncHandler(async (req, res) => {
            if (!needRevisionStore(res)) {
                return
            }
            const rev = await opts.revisions!.getRevision(req.params.id)
            if (!rev) {
                res.status(404).json({ error: 'revision_not_found' })
                return
            }
            const entries = await opts.bundles!.list(req.params.id)
            res.json({
                revision_id: req.params.id,
                state: rev.state,
                bundle_sha256: rev.bundle_sha256,
                files: entries,
            })
        })
    )

    app.get(
        '/revisions/:id/file',
        asyncHandler(async (req, res) => {
            if (!needRevisionStore(res)) {
                return
            }
            const { path } = FilePathQuerySchema.parse(req.query)
            if (!(await opts.bundles!.exists(req.params.id, path))) {
                res.status(404).json({ error: 'file_not_found' })
                return
            }
            const text = await opts.bundles!.readText(req.params.id, path)
            res.json({ path, content: text })
        })
    )

    app.put(
        '/revisions/:id/file',
        asyncHandler(async (req, res) => {
            if (!needRevisionStore(res)) {
                return
            }
            const { path } = FilePathQuerySchema.parse(req.query)
            const { content } = FileUpdateBodySchema.parse(req.body)
            const ok = await requireDraft(res, req.params.id)
            if (!ok) {
                return
            }
            await opts.bundles!.write(req.params.id, path, content)
            res.json({ ok: true, path, bytes: Buffer.byteLength(content, 'utf8') })
        })
    )

    app.delete(
        '/revisions/:id/file',
        asyncHandler(async (req, res) => {
            if (!needRevisionStore(res)) {
                return
            }
            const { path } = FilePathQuerySchema.parse(req.query)
            const ok = await requireDraft(res, req.params.id)
            if (!ok) {
                return
            }
            await opts.bundles!.delete(req.params.id, path)
            res.json({ ok: true, path })
        })
    )

    app.get(
        '/revisions/:id/bundle',
        asyncHandler(async (req, res) => {
            if (!needRevisionStore(res)) {
                return
            }
            const rev = await opts.revisions!.getRevision(req.params.id)
            if (!rev) {
                res.status(404).json({ error: 'revision_not_found' })
                return
            }
            const entries = await opts.bundles!.list(req.params.id)
            const files: Record<string, string> = {}
            for (const e of entries) {
                files[e.path] = await opts.bundles!.readText(req.params.id, e.path)
            }
            res.json({
                revision_id: req.params.id,
                state: rev.state,
                bundle_sha256: rev.bundle_sha256,
                files,
            })
        })
    )

    app.put(
        '/revisions/:id/bundle',
        asyncHandler(async (req, res) => {
            if (!needRevisionStore(res)) {
                return
            }
            const { files, mode } = BundlePutBodySchema.parse(req.body)
            const ok = await requireDraft(res, req.params.id)
            if (!ok) {
                return
            }
            if (mode === 'replace') {
                // Wipe everything before writing the new set. Keeps the bundle
                // in lockstep with what the caller declared.
                const existing = await opts.bundles!.list(req.params.id)
                for (const e of existing) {
                    await opts.bundles!.delete(req.params.id, e.path)
                }
            }
            for (const [p, content] of Object.entries(files)) {
                await opts.bundles!.write(req.params.id, p, content)
            }
            const listed = await opts.bundles!.list(req.params.id)
            res.json({ ok: true, mode, files: listed })
        })
    )

    app.post(
        '/revisions/:id/freeze',
        asyncHandler(async (req, res) => {
            if (!needRevisionStore(res)) {
                return
            }
            const ok = await requireDraft(res, req.params.id)
            if (!ok) {
                return
            }
            // Validate before freezing — freeze is the contract that says
            // "this is a real candidate for running." A revision that would
            // fail validation can't pass that gate; otherwise we'd ship dead
            // agents like the original Hedgebox Helper v2 (empty triggers).
            const report = await validateRevisionBundle(ok.rev!, opts.bundles!)
            if (!report.ok) {
                res.status(422).json({ error: 'validation_failed', report })
                return
            }
            const sha = await opts.bundles!.freeze(req.params.id)
            // Stamp the sha + flip the row to `ready` so the runner can pick it
            // up via `setLiveRevision` later. Two writes; the second is the
            // user-visible state change.
            await opts.revisions!.setRevisionState(req.params.id, 'ready', sha)
            res.json({ ok: true, state: 'ready', bundle_sha256: sha })
        })
    )

    app.post(
        '/revisions/:id/validate',
        asyncHandler(async (req, res) => {
            if (!needRevisionStore(res)) {
                return
            }
            const rev = await opts.revisions!.getRevision(req.params.id)
            if (!rev) {
                res.status(404).json({ error: 'revision_not_found' })
                return
            }
            const report = await validateRevisionBundle(rev, opts.bundles!)
            res.json(report)
        })
    )

    // Manually fire one cron job — same execution path the scheduler walks,
    // but on demand. Authoring path: the user clicks "fire now" in the
    // console (or the concierge MCP tool
    // `agent-applications-revisions-cron-fire-create`) and gets back the
    // session id without having to wait for the next real firing. Without
    // this, "did my cron prompt do the right thing?" is unanswerable until
    // the cron actually fires. Plan §9 "Manual fire".
    //
    // Dedupe shape `cron-manual:<rev>:<name>:<request_id>` — distinct from
    // the scheduled `cron:<rev>:<name>:<minute>` form, so manual + scheduled
    // firings at the same minute don't collide. The caller can supply
    // `request_id` to make repeated clicks idempotent (the UI does this);
    // omitting it generates a fresh UUID, which makes every call a new fire.
    app.post(
        '/revisions/:id/cron/fire',
        asyncHandler(async (req, res) => {
            if (!needRevisionStore(res)) {
                return
            }
            const rev = await opts.revisions!.getRevision(req.params.id)
            if (!rev) {
                res.status(404).json({ error: 'revision_not_found' })
                return
            }
            const app_ = await opts.revisions!.getApplication(rev.application_id)
            if (!app_) {
                res.status(404).json({ error: 'application_not_found' })
                return
            }
            const body = CronFireBodySchema.parse(req.body)
            const trigger = rev.spec.triggers.find((t) => t.type === 'cron' && t.config.name === body.cron_name)
            if (!trigger || trigger.type !== 'cron') {
                res.status(404).json({ error: 'unknown_cron', cron_name: body.cron_name })
                return
            }
            const requestId = body.request_id ?? randomUUID()
            const result = await fireCronManually(
                { revisions: opts.revisions!, queue: opts.queue },
                {
                    rev,
                    app: app_,
                    cronName: body.cron_name,
                    requestId,
                    firedAt: body.fired_at ? new Date(body.fired_at) : undefined,
                }
            )
            res.json({ ok: true, ...result, request_id: requestId })
        })
    )

    // Render the fully-assembled system prompt for a revision —
    // framework preamble + agent.md + skills index. Authors (via the
    // Django proxy / MCP) use this to inspect what the model will
    // actually see before promotion. Plan §4 (framework-system-prompt.md).
    app.get(
        '/revisions/:id/system-prompt',
        asyncHandler(async (req, res) => {
            if (!needRevisionStore(res)) {
                return
            }
            const rev = await opts.revisions!.getRevision(req.params.id)
            if (!rev) {
                res.status(404).json({ error: 'revision_not_found' })
                return
            }
            const systemPrompt = await buildSystemPrompt(rev, opts.bundles!)
            res.json({
                revision_id: req.params.id,
                framework_prompt_version: FRAMEWORK_PROMPT_VERSION,
                system_prompt: systemPrompt,
            })
        })
    )

    app.post(
        '/revisions/:id/clone_from',
        asyncHandler(async (req, res) => {
            if (!needRevisionStore(res)) {
                return
            }
            const { source_revision_id: sourceId } = CloneFromBodySchema.parse(req.body)
            const ok = await requireDraft(res, req.params.id)
            if (!ok) {
                return
            }
            const src = await opts.bundles!.list(sourceId)
            for (const entry of src) {
                await opts.bundles!.copy(sourceId, entry.path, req.params.id, entry.path)
            }
            const files = await opts.bundles!.list(req.params.id)
            res.json({ ok: true, source_revision_id: sourceId, files })
        })
    )

    /* ──────────────────────── extracted route groups ───────────────────── */
    //
    // First step of the api/-folder refactor — memory routes live in
    // src/api/memory.ts. The remaining groups (sessions, approvals,
    // revisions, applications, native-tools) still inline above; same
    // pattern applies when they get extracted: one file per logical group,
    // each exporting `mount*Routes(app, opts, log)` called here.
    mountMemoryRoutes(app, { memoryStore: opts.memoryStore, log })

    // Last in the chain. Catches anything the route handlers threw (via
    // asyncHandler), translates ZodError → 400, everything else → 500.
    app.use(errorHandler(log))

    return app
}

function usageMatches(a: typeof EMPTY_USAGE_TOTAL, b: typeof EMPTY_USAGE_TOTAL): boolean {
    return (
        a.tokens_in === b.tokens_in &&
        a.tokens_out === b.tokens_out &&
        a.cache_read === b.cache_read &&
        a.cache_write === b.cache_write &&
        a.cost_input === b.cost_input &&
        a.cost_output === b.cost_output &&
        a.cost_cache_read === b.cost_cache_read &&
        a.cost_cache_write === b.cost_cache_write &&
        a.cost_total === b.cost_total
    )
}
