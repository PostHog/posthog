import { MemoryBundleStore } from './memory-bundle-store'

describe('MemoryBundleStore', () => {
    let store: MemoryBundleStore

    beforeEach(() => {
        store = new MemoryBundleStore()
    })

    it('writes, reads, and lists files', async () => {
        await store.write('rev1', 'agent.md', '# hello')
        await store.write('rev1', 'skills/a.md', 'skill a')
        const all = await store.list('rev1')
        expect(all.map((e) => e.path)).toEqual(['agent.md', 'skills/a.md'])
        expect(await store.readText('rev1', 'agent.md')).toBe('# hello')
    })

    it('filters list by prefix', async () => {
        await store.write('rev1', 'agent.md', 'x')
        await store.write('rev1', 'skills/a.md', 'x')
        await store.write('rev1', 'skills/b.md', 'x')
        const skills = await store.list('rev1', 'skills/')
        expect(skills.map((e) => e.path)).toEqual(['skills/a.md', 'skills/b.md'])
    })

    it('freezes and blocks further writes', async () => {
        await store.write('rev1', 'agent.md', 'x')
        const sha = await store.freeze('rev1')
        expect(sha).toMatch(/^[a-f0-9]{64}$/)
        await expect(store.write('rev1', 'agent.md', 'y')).rejects.toThrow(/frozen/)
    })

    it('freeze sha changes when content changes', async () => {
        await store.write('rev1', 'agent.md', 'x')
        await store.write('rev2', 'agent.md', 'y')
        const sha1 = await store.freeze('rev1')
        const sha2 = await store.freeze('rev2')
        expect(sha1).not.toBe(sha2)
    })

    it('copies a file between revisions', async () => {
        await store.write('rev1', 'tools/x/source.ts', 'export const x = 1')
        await store.copy('rev1', 'tools/x/source.ts', 'rev2', 'tools/y/source.ts')
        expect(await store.readText('rev2', 'tools/y/source.ts')).toBe('export const x = 1')
    })

    it('exists/delete behave correctly', async () => {
        await store.write('rev1', 'f.txt', 'x')
        expect(await store.exists('rev1', 'f.txt')).toBe(true)
        await store.delete('rev1', 'f.txt')
        expect(await store.exists('rev1', 'f.txt')).toBe(false)
    })
})
