import { post, readPrincipal } from '../../harness/clients'
/**
 * Caller-auth e2e — one suite per policy. Each case posts to `/run` against
 * a freshly created app fixture, asserts the ingress response, and (for
 * happy paths) checks the principal stamped on the queue row.
 *
 * Doesn't always wait for the runner; many failure cases never enqueue so
 * there's nothing to dequeue. The runtime path is exercised in
 * `runtime.test.ts` — this file focuses on Layer-1 caller-auth behaviour.
 */
import { type AgentCluster, openSharedCluster } from '../../harness/cluster'
import { createApp, setTeamSecret } from '../../harness/fixtures'

const TEAM_SECRET = 'e2e-auth-team-secret'
const SHARED_SECRET_ENV = 'E2E_SHARED_SECRET'
const SHARED_SECRET_VALUE = 'e2e-shared-secret-value'
// The shared-secret value lives in the app's encrypted_env now (was a
// global override on the per-suite cluster). The ingress's default
// loadSecret reads the app's env via `repository.decryptEnv`, so each
// app that uses `shared_secret` auth puts the value in its own env.
const SHARED_SECRET_APP_ENV = { [SHARED_SECRET_ENV]: SHARED_SECRET_VALUE }

describe('caller-auth e2e', () => {
    let cluster: AgentCluster

    beforeAll(async () => {
        cluster = await openSharedCluster()
        await setTeamSecret(cluster.cleanup, TEAM_SECRET)
    }, 30_000)

    afterAll(async () => {
        await cluster?.cleanup.runAll()
    }, 30_000)

    /* ===== public ===== */

    describe('public', () => {
        it('enqueues without auth; no principal stamped', async () => {
            const app = await createApp(cluster.cleanup, { slugSuffix: 'public', auth: { type: 'public' } })
            const res = await post(cluster, app.slug)
            expect(res.status).toBe(202)
            expect(await readPrincipal(cluster, res.body.sessionId)).toBeNull()
        })
    })

    /* ===== pat ===== */

    describe('pat', () => {
        it('happy: correct token → 202 + service principal stamped', async () => {
            const app = await createApp(cluster.cleanup, { slugSuffix: 'pat-ok', auth: { type: 'pat' } })
            const res = await post(cluster, app.slug, { pat: TEAM_SECRET })
            expect(res.status).toBe(202)
            expect(await readPrincipal(cluster, res.body.sessionId)).toEqual({
                kind: 'service',
                orgId: '1',
                caller: 'team-secret',
            })
        })

        it('wrong token → 401', async () => {
            const app = await createApp(cluster.cleanup, { slugSuffix: 'pat-wrong', auth: { type: 'pat' } })
            const res = await post(cluster, app.slug, { pat: 'not-the-team-secret' })
            expect(res.status).toBe(401)
        })

        it('missing token → 401', async () => {
            const app = await createApp(cluster.cleanup, { slugSuffix: 'pat-missing', auth: { type: 'pat' } })
            const res = await post(cluster, app.slug)
            expect(res.status).toBe(401)
        })
    })

    /* ===== posthog_internal ===== */

    describe('posthog_internal', () => {
        it('happy: correct internal header → 202 + posthog-internal principal stamped', async () => {
            const app = await createApp(cluster.cleanup, {
                slugSuffix: 'internal-ok',
                auth: { type: 'posthog_internal' },
            })
            const res = await post(cluster, app.slug, { internalSecret: cluster.internalSecret })
            expect(res.status).toBe(202)
            expect(await readPrincipal(cluster, res.body.sessionId)).toEqual({
                kind: 'service',
                orgId: 'posthog',
                caller: 'posthog-internal',
            })
        })

        it('missing internal header → 403', async () => {
            const app = await createApp(cluster.cleanup, {
                slugSuffix: 'internal-missing',
                auth: { type: 'posthog_internal' },
            })
            const res = await post(cluster, app.slug)
            expect(res.status).toBe(403)
        })
    })

    /* ===== shared_secret ===== */

    describe('shared_secret', () => {
        it('happy: correct header → 202 + synthesised principal', async () => {
            const app = await createApp(cluster.cleanup, {
                slugSuffix: 'shared-ok',
                auth: { type: 'shared_secret', secret_name: SHARED_SECRET_ENV, header: 'x-shared-secret' },
                encryptedEnv: SHARED_SECRET_APP_ENV,
            })
            const res = await post(cluster, app.slug, {
                sharedSecret: { header: 'x-shared-secret', value: SHARED_SECRET_VALUE },
            })
            expect(res.status).toBe(202)
            expect(await readPrincipal(cluster, res.body.sessionId)).toEqual({
                kind: 'service',
                orgId: 'shared-secret',
                caller: `shared_secret:${SHARED_SECRET_ENV}`,
            })
        })

        it('wrong header value → 401', async () => {
            const app = await createApp(cluster.cleanup, {
                slugSuffix: 'shared-wrong',
                auth: { type: 'shared_secret', secret_name: SHARED_SECRET_ENV, header: 'x-shared-secret' },
                encryptedEnv: SHARED_SECRET_APP_ENV,
            })
            const res = await post(cluster, app.slug, {
                sharedSecret: { header: 'x-shared-secret', value: 'wrong' },
            })
            expect(res.status).toBe(401)
        })

        it('missing header → 401', async () => {
            const app = await createApp(cluster.cleanup, {
                slugSuffix: 'shared-missing',
                auth: { type: 'shared_secret', secret_name: SHARED_SECRET_ENV, header: 'x-shared-secret' },
                encryptedEnv: SHARED_SECRET_APP_ENV,
            })
            const res = await post(cluster, app.slug)
            expect(res.status).toBe(401)
        })
    })
})
