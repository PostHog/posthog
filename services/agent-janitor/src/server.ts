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
import { z } from 'zod'

import {
    accumulateUsage,
    AgentSession,
    BundleStore,
    createLogger,
    EMPTY_USAGE_TOTAL,
    lastAssistantTextPreview,
    RevisionStore,
    SessionQueue,
} from '@posthog/agent-shared'
import { listNativeTools } from '@posthog/agent-tools'

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
    internalSecret?: string
}

const SessionStateSchema = z.enum(['queued', 'running', 'waiting', 'completed', 'failed'])

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

const FileUpdateBodySchema = z.object({
    content: z.string(),
})

const BundleFilesSchema = z.record(z.string(), z.string())
const BundlePutBodySchema = z.object({
    files: BundleFilesSchema,
    mode: z.enum(['replace', 'merge']).default('replace'),
})

const CloneFromBodySchema = z.object({
    source_revision_id: z.string().min(1, 'missing_source_revision_id'),
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
            const sessions = await opts.queue.listByApplication(q.application_id, {
                limit: q.limit,
                offset: q.offset,
                states: q.state as AgentSession['state'][] | undefined,
                revisionId: q.revision_id,
                createdAfter: q.created_after,
                createdBefore: q.created_before,
            })
            // Conversation can be large; strip it from the list view but derive a
            // preview so a single tool call still tells you what the agent said.
            // usage_total reads off the persisted column — no JSONB walk.
            const summaries = sessions.map((s) => ({
                id: s.id,
                application_id: s.application_id,
                revision_id: s.revision_id,
                state: s.state,
                external_key: s.external_key,
                principal: s.principal,
                turns: s.conversation.length,
                preview: lastAssistantTextPreview(s.conversation),
                usage_total: s.usage_total,
                retry_count: s.retry_count,
                created_at: s.created_at,
                updated_at: s.updated_at,
            }))
            res.json({ sessions: summaries })
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
            await opts.queue.update(req.params.id, { state: 'failed' })
            res.json({ ok: true })
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
