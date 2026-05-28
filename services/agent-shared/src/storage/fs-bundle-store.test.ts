import { promises as fs } from 'fs'
import * as os from 'os'
import * as path from 'path'

import { FsBundleStore } from './fs-bundle-store'

describe('FsBundleStore', () => {
    let root: string
    let store: FsBundleStore

    beforeEach(async () => {
        root = await fs.mkdtemp(path.join(os.tmpdir(), 'bundle-test-'))
        store = new FsBundleStore(root)
    })

    afterEach(async () => {
        await fs.rm(root, { recursive: true, force: true })
    })

    it('writes, reads, and lists files (nested paths)', async () => {
        await store.write('rev1', 'agent.md', '# hello')
        await store.write('rev1', 'skills/research.md', 'be thorough')
        await store.write('rev1', 'tools/x/source.ts', '// x')
        const all = await store.list('rev1')
        expect(all.map((e) => e.path).sort()).toEqual(['agent.md', 'skills/research.md', 'tools/x/source.ts'])
        expect(await store.readText('rev1', 'skills/research.md')).toBe('be thorough')
    })

    it('filters by prefix', async () => {
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

    it('copy between revisions', async () => {
        await store.write('rev1', 'agent.md', 'shared')
        await store.copy('rev1', 'agent.md', 'rev2', 'agent.md')
        expect(await store.readText('rev2', 'agent.md')).toBe('shared')
    })

    it("rejects '..' in paths", async () => {
        await expect(store.write('rev1', '../escape.txt', 'x')).rejects.toThrow(/invalid path/)
    })

    it('delete', async () => {
        await store.write('rev1', 'f.txt', 'x')
        expect(await store.exists('rev1', 'f.txt')).toBe(true)
        await store.delete('rev1', 'f.txt')
        expect(await store.exists('rev1', 'f.txt')).toBe(false)
    })
})
