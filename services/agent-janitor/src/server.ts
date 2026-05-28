/**
 * Internal HTTP for Django. The janitor doubles as the agent-admin surface
 * because (a) it already runs as a deploy unit, (b) it already has DB +
 * bundle store access, (c) auth is one shared internal secret.
 *
 * Endpoints (grouped):
 *
 *   Session lifecycle (existing):
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
 */

import express, { Express, NextFunction, Request, Response } from 'express'

import { BundleStore, RevisionStore, SessionQueue } from '@posthog/agent-shared'
import { listNativeTools } from '@posthog/agent-tools'

import { SweepDeps, sweepOnce } from './sweep'

export interface JanitorServerOpts {
    queue: SessionQueue
    sweep: SweepDeps
    /** Required for the /revisions/* + /native_tools endpoints. */
    revisions?: RevisionStore
    bundles?: BundleStore
    internalSecret?: string
}

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

    app.get('/sessions/:id', async (req, res) => {
        const s = await opts.queue.get(req.params.id)
        if (!s) {
            res.status(404).json({ error: 'not_found' })
            return
        }
        res.json(s)
    })
    app.post('/sessions/:id/cancel', async (req, res) => {
        const s = await opts.queue.get(req.params.id)
        if (!s) {
            res.status(404).json({ error: 'not_found' })
            return
        }
        await opts.queue.update(req.params.id, { state: 'failed' })
        res.json({ ok: true })
    })
    app.post('/sweep', async (_req, res) => {
        const result = await sweepOnce(opts.sweep)
        res.json(result)
    })

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

    app.get('/revisions/:id/manifest', async (req, res) => {
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

    app.get('/revisions/:id/file', async (req, res) => {
        if (!needRevisionStore(res)) {
            return
        }
        const path = String(req.query.path ?? '')
        if (!path) {
            res.status(400).json({ error: 'missing_path' })
            return
        }
        if (!(await opts.bundles!.exists(req.params.id, path))) {
            res.status(404).json({ error: 'file_not_found' })
            return
        }
        const text = await opts.bundles!.readText(req.params.id, path)
        res.json({ path, content: text })
    })

    app.put('/revisions/:id/file', async (req, res) => {
        if (!needRevisionStore(res)) {
            return
        }
        const path = String(req.query.path ?? '')
        const content = (req.body as { content?: string } | undefined)?.content
        if (!path || typeof content !== 'string') {
            res.status(400).json({ error: 'missing_path_or_content' })
            return
        }
        const ok = await requireDraft(res, req.params.id)
        if (!ok) {
            return
        }
        await opts.bundles!.write(req.params.id, path, content)
        res.json({ ok: true, path, bytes: Buffer.byteLength(content, 'utf8') })
    })

    app.delete('/revisions/:id/file', async (req, res) => {
        if (!needRevisionStore(res)) {
            return
        }
        const path = String(req.query.path ?? '')
        if (!path) {
            res.status(400).json({ error: 'missing_path' })
            return
        }
        const ok = await requireDraft(res, req.params.id)
        if (!ok) {
            return
        }
        await opts.bundles!.delete(req.params.id, path)
        res.json({ ok: true, path })
    })

    app.get('/revisions/:id/bundle', async (req, res) => {
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

    app.put('/revisions/:id/bundle', async (req, res) => {
        if (!needRevisionStore(res)) {
            return
        }
        const body = req.body as { files?: Record<string, string>; mode?: 'replace' | 'merge' }
        if (!body?.files || typeof body.files !== 'object') {
            res.status(400).json({ error: 'missing_files' })
            return
        }
        const mode = body.mode ?? 'replace'
        if (mode !== 'replace' && mode !== 'merge') {
            res.status(400).json({ error: 'invalid_mode' })
            return
        }
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
        for (const [p, content] of Object.entries(body.files)) {
            await opts.bundles!.write(req.params.id, p, content)
        }
        const files = await opts.bundles!.list(req.params.id)
        res.json({ ok: true, mode, files })
    })

    app.post('/revisions/:id/freeze', async (req, res) => {
        if (!needRevisionStore(res)) {
            return
        }
        const ok = await requireDraft(res, req.params.id)
        if (!ok) {
            return
        }
        const sha = await opts.bundles!.freeze(req.params.id)
        // Stamp the sha + flip the row to `ready` so the runner can pick it
        // up via `setLiveRevision` later. Two writes; the second is the
        // user-visible state change.
        await opts.revisions!.setRevisionState(req.params.id, 'ready', sha)
        res.json({ ok: true, state: 'ready', bundle_sha256: sha })
    })

    app.post('/revisions/:id/clone_from', async (req, res) => {
        if (!needRevisionStore(res)) {
            return
        }
        const body = req.body as { source_revision_id?: string }
        const sourceId = body?.source_revision_id
        if (!sourceId) {
            res.status(400).json({ error: 'missing_source_revision_id' })
            return
        }
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

    return app
}
