/**
 * Regression: `resolveAgent` accepts the preview JWT from either the
 * `x-agent-preview-token` header (POST/DELETE + server-side proxy) or
 * the `?preview_token=` query parameter (browser `EventSource` for
 * `/listen`, since EventSource can't set custom headers).
 *
 * The token-claim verification lives in `RevisionResolver.assertPreviewGate`
 * and is covered separately in `resolver.test.ts`. These tests only assert
 * the dual-source extraction in `resolveAgent` itself — i.e. that an
 * EventSource caller can replace the missing header with a query param.
 */

import type { Request, Response } from 'express'
import { SignJWT } from 'jose'

import { AgentRevision, AgentSpecSchema, MemoryRevisionStore } from '@posthog/agent-shared'

import { RevisionResolver } from '../routing/resolver'
import { resolveAgent } from './resolve'

const SECRET = 'test-preview-secret-test-preview-secret'
// Mirrors the (currently unexported) constant in routing/resolver.ts
// — `aud` must match the one the resolver hands to `jwtVerify`.
const PREVIEW_TOKEN_AUDIENCE = 'posthog:agent_preview'

// UUID-shaped id so the resolver's `<slug>-<8..32 hex>` regex matches.
const DRAFT_UUID = '019e74a3-57d4-78f3-86a0-7e7135a96d80'
const DRAFT_HEX = DRAFT_UUID.replace(/-/g, '')

async function mintToken(secret: string, claims: { app: string; rev: string; audience?: string }): Promise<string> {
    return new SignJWT({ app: claims.app, rev: claims.rev })
        .setProtectedHeader({ alg: 'HS256' })
        .setAudience(claims.audience ?? PREVIEW_TOKEN_AUDIENCE)
        .setExpirationTime('60s')
        .sign(new TextEncoder().encode(secret))
}

/** MemoryRevisionStore generates `rev_N` ids by default; force a UUID-shaped one. */
function rebrand(store: MemoryRevisionStore, oldId: string, newId: string): void {
    const map = (store as unknown as { revs: Map<string, AgentRevision> }).revs
    const rev = map.get(oldId)
    if (!rev) {
        throw new Error(`revision ${oldId} not found`)
    }
    rev.id = newId
    map.delete(oldId)
    map.set(newId, rev)
}

async function seedDraft(store: MemoryRevisionStore, slug: string): Promise<{ appId: string }> {
    const app = await store.createApplication({ team_id: 1, slug, name: slug, description: '' })
    const live = await store.createRevision({
        application_id: app.id,
        parent_revision_id: null,
        created_by_id: null,
        bundle_uri: 's3://x/',
        spec: AgentSpecSchema.parse({ model: 'x' }),
    })
    await store.setRevisionState(live.id, 'live')
    await store.setLiveRevision(app.id, live.id)
    const draft = await store.createRevision({
        application_id: app.id,
        parent_revision_id: null,
        created_by_id: null,
        bundle_uri: 's3://x/',
        spec: AgentSpecSchema.parse({ model: 'x' }),
    })
    rebrand(store, draft.id, DRAFT_UUID)
    return { appId: app.id }
}

function mkResolver(store: MemoryRevisionStore): RevisionResolver {
    return new RevisionResolver({
        revisions: store,
        mode: 'path',
        pathPrefix: '/agents',
        teamId: 1,
        previewSecret: SECRET,
    })
}

interface CapturedResponse {
    status: number | null
    body: unknown
}

function fakeRes(): { res: Response; captured: CapturedResponse } {
    const captured: CapturedResponse = { status: null, body: null }
    const res = {
        status(n: number) {
            captured.status = n
            return this
        },
        json(body: unknown) {
            captured.body = body
            return this
        },
    } as unknown as Response
    return { res, captured }
}

function fakeReq(opts: { slug: string; header?: string; queryToken?: string }): Request {
    return {
        params: { slug: opts.slug },
        headers: opts.header ? { 'x-agent-preview-token': opts.header } : {},
        query: opts.queryToken ? { preview_token: opts.queryToken } : {},
    } as unknown as Request
}

describe('resolveAgent (preview token source)', () => {
    it('admits a draft invoke when the JWT arrives in the `x-agent-preview-token` header', async () => {
        const store = new MemoryRevisionStore()
        const { appId } = await seedDraft(store, 'gated')
        const token = await mintToken(SECRET, { app: appId, rev: DRAFT_UUID })
        const { res, captured } = fakeRes()

        const out = await resolveAgent(mkResolver(store), fakeReq({ slug: `gated-${DRAFT_HEX}`, header: token }), res)

        expect(out?.revision.id).toBe(DRAFT_UUID)
        expect(captured.status).toBeNull()
    })

    it('admits a draft invoke when the JWT arrives as `?preview_token=` (EventSource path)', async () => {
        // EventSource cannot set custom headers, so the browser puts
        // the JWT in the URL. This is the regression cover for the
        // direct-to-ingress preview-token architecture.
        const store = new MemoryRevisionStore()
        const { appId } = await seedDraft(store, 'gated')
        const token = await mintToken(SECRET, { app: appId, rev: DRAFT_UUID })
        const { res, captured } = fakeRes()

        const out = await resolveAgent(
            mkResolver(store),
            fakeReq({ slug: `gated-${DRAFT_HEX}`, queryToken: token }),
            res
        )

        expect(out?.revision.id).toBe(DRAFT_UUID)
        expect(captured.status).toBeNull()
    })

    it('header wins over query string when both are present', async () => {
        const store = new MemoryRevisionStore()
        const { appId } = await seedDraft(store, 'gated')
        const goodToken = await mintToken(SECRET, { app: appId, rev: DRAFT_UUID })
        const badQueryToken = await mintToken('different-secret', { app: appId, rev: DRAFT_UUID })
        const { res, captured } = fakeRes()

        const out = await resolveAgent(
            mkResolver(store),
            fakeReq({ slug: `gated-${DRAFT_HEX}`, header: goodToken, queryToken: badQueryToken }),
            res
        )

        expect(out?.revision.id).toBe(DRAFT_UUID)
        expect(captured.status).toBeNull()
    })

    it('returns 401 with `preview_token_required` when neither source carries a token', async () => {
        const store = new MemoryRevisionStore()
        await seedDraft(store, 'gated')
        const { res, captured } = fakeRes()

        const out = await resolveAgent(mkResolver(store), fakeReq({ slug: `gated-${DRAFT_HEX}` }), res)

        expect(out).toBeNull()
        expect(captured.status).toBe(401)
        expect((captured.body as { error?: string }).error).toBe('preview_token_required')
    })
})
