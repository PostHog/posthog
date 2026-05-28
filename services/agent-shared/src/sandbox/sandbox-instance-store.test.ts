import { MemorySandboxInstanceStore } from './sandbox-instance-store'

describe('MemorySandboxInstanceStore', () => {
    function fresh(): MemorySandboxInstanceStore {
        return new MemorySandboxInstanceStore()
    }
    const base = {
        team_id: 1,
        application_id: 'app-1',
        revision_id: 'rev-1',
        session_id: 'sess-1',
        provider_kind: 'docker' as const,
    }

    it('create() inserts a provisioning row with the chosen provider_kind', async () => {
        const s = fresh()
        const row = await s.create(base)
        expect(row.state).toBe('provisioning')
        expect(row.provider_kind).toBe('docker')
        expect(row.provider_sandbox_id).toBe('')
        expect(await s.get(row.id)).not.toBeNull()
    })

    it('markReady transitions provisioning → ready and records the provider id', async () => {
        const s = fresh()
        const row = await s.create(base)
        await s.markReady(row.id, 'container-abc')
        const after = await s.get(row.id)
        expect(after!.state).toBe('ready')
        expect(after!.provider_sandbox_id).toBe('container-abc')
        expect(after!.last_used_at).not.toBeNull()
    })

    it('markFailed records the error message (truncated to 4000 chars) and sets terminated_at', async () => {
        const s = fresh()
        const row = await s.create(base)
        const longMessage = 'x'.repeat(5000)
        await s.markFailed(row.id, longMessage)
        const after = await s.get(row.id)
        expect(after!.state).toBe('failed')
        expect(after!.error_message).toHaveLength(4000)
        expect(after!.terminated_at).not.toBeNull()
    })

    it('markTerminated moves ready → terminated and stamps terminated_at', async () => {
        const s = fresh()
        const row = await s.create(base)
        await s.markReady(row.id, 'cid')
        await s.markTerminated(row.id)
        const after = await s.get(row.id)
        expect(after!.state).toBe('terminated')
        expect(after!.terminated_at).not.toBeNull()
    })

    it('findStale: rows older than maxAge in alive states are returned; terminated/failed are skipped', async () => {
        const s = fresh()
        // 1. Stale ready row.
        const stale = await s.create(base)
        await s.markReady(stale.id, 'cid-stale')
        const r = await s.get(stale.id)
        ;(r as { last_used_at: string }).last_used_at = new Date(Date.now() - 60 * 60_000).toISOString()
        // 2. Fresh ready row.
        const fresh1 = await s.create(base)
        await s.markReady(fresh1.id, 'cid-fresh')
        // 3. Terminated (alive cutoff doesn't apply).
        const dead = await s.create(base)
        await s.markTerminated(dead.id)

        const stales = await s.findStale(60_000)
        expect(stales).toHaveLength(1)
        expect(stales[0].id).toBe(stale.id)
        expect(stales[0].provider_sandbox_id).toBe('cid-stale')
    })
})
