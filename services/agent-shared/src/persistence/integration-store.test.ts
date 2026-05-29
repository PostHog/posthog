import { MemoryIntegrationStore } from './integration-store'

describe('MemoryIntegrationStore', () => {
    function makeStore(): MemoryIntegrationStore {
        const s = new MemoryIntegrationStore()
        s.add(1, 'slack', 'T01ACME', { kind: 'slack', access_token: 'xoxb-acme' })
        s.add(1, 'slack', 'T02BETA', { kind: 'slack', access_token: 'xoxb-beta' })
        s.add(1, 'github', 'acme-org', {
            kind: 'github',
            access_token: 'gh_main',
            refresh_token: 'gh_refresh',
            metadata: { repos: ['acme/api'] },
        })
        s.add(2, 'slack', 'T03OTHER', { kind: 'slack', access_token: 'xoxb-other-team' })
        return s
    }

    it('get returns the row by natural key', async () => {
        const store = makeStore()
        const creds = await store.get(1, 'slack', 'T01ACME')
        expect(creds?.access_token).toBe('xoxb-acme')
    })

    it('get returns null for an unknown row', async () => {
        const store = makeStore()
        expect(await store.get(1, 'slack', 'NOT_THERE')).toBeNull()
        expect(await store.get(99, 'slack', 'T01ACME')).toBeNull()
    })

    it('list returns every connected integration of one kind for one team', async () => {
        const store = makeStore()
        const rows = await store.list(1, 'slack')
        expect(rows.map((r) => r.integration_id).sort()).toEqual(['T01ACME', 'T02BETA'])
        // Cross-team rows are NOT included.
        expect(rows.find((r) => r.credentials.access_token === 'xoxb-other-team')).toBeUndefined()
    })

    it('resolveForSpec returns a kind:id-keyed credentials map', async () => {
        const store = makeStore()
        const out = await store.resolveForSpec(1, ['slack', 'github'])
        expect(Object.keys(out).sort()).toEqual(['github:acme-org', 'slack:T01ACME', 'slack:T02BETA'])
        expect(out['github:acme-org'].refresh_token).toBe('gh_refresh')
        expect(out['github:acme-org'].metadata).toEqual({ repos: ['acme/api'] })
    })

    it('resolveForSpec silently omits kinds the team has no integration for', async () => {
        const store = makeStore()
        const out = await store.resolveForSpec(1, ['slack', 'linear', 'github'])
        expect(Object.keys(out).sort()).toEqual(['github:acme-org', 'slack:T01ACME', 'slack:T02BETA'])
        // No `linear:*` key — the tool's "integration not connected" error
        // surfaces at call time, the resolver doesn't pre-fail.
        expect(Object.keys(out).some((k) => k.startsWith('linear'))).toBe(false)
    })

    it('resolveForSpec on an empty kinds list returns an empty map', async () => {
        const store = makeStore()
        expect(await store.resolveForSpec(1, [])).toEqual({})
    })

    it('add() replaces an existing row at the same natural key', async () => {
        const store = makeStore()
        store.add(1, 'slack', 'T01ACME', { kind: 'slack', access_token: 'xoxb-rotated' })
        expect((await store.get(1, 'slack', 'T01ACME'))?.access_token).toBe('xoxb-rotated')
        // Still only one Slack row per integration_id for team 1.
        expect((await store.list(1, 'slack')).length).toBe(2)
    })
})
