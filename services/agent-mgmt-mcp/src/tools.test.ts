import { MemoryBundleStore, MemoryRevisionStore } from '@posthog/agent-shared-v2'

import { SimpleCompiler } from './compile'
import {
    AgentMgmtDeps,
    archiveAgent,
    copyFile,
    createRevision,
    deleteFile,
    deployRevision,
    diffRevisions,
    getAgent,
    getRevision,
    listAgents,
    listAvailableTools,
    listFiles,
    promoteRevision,
    readFile,
    updateSpec,
    writeFile,
} from './tools'

function mkDeps(): AgentMgmtDeps {
    return {
        revisions: new MemoryRevisionStore(),
        bundle: new MemoryBundleStore(),
        compiler: new SimpleCompiler(),
        teamId: 1,
        userId: 'u1',
    }
}

describe('agent_mgmt CRUD', () => {
    it('create_revision creates the application + draft revision and seeds agent.md', async () => {
        const deps = mkDeps()
        const out = await createRevision(deps, { slug: 'weekly-digest' })
        expect(out.application_id).not.toBeUndefined()
        expect(out.revision_id).not.toBeUndefined()
        expect(await deps.bundle.exists(out.revision_id, 'agent.md')).toBe(true)
    })

    it('create_revision with parent_revision_id copies the parent bundle', async () => {
        const deps = mkDeps()
        const first = await createRevision(deps, { slug: 'x' })
        await writeFile(deps, { rev_id: first.revision_id, path: 'skills/research.md', content: 'be thorough' })
        await promoteRevision(deps, { rev_id: first.revision_id })
        const second = await createRevision(deps, { slug: 'x', parent_revision_id: first.revision_id })
        expect(await deps.bundle.exists(second.revision_id, 'skills/research.md')).toBe(true)
    })

    it('list_agents returns deployed agents', async () => {
        const deps = mkDeps()
        await createRevision(deps, { slug: 'a' })
        await createRevision(deps, { slug: 'b' })
        const out = await listAgents(deps)
        expect(out.map((a) => a.slug).sort()).toEqual(['a', 'b'])
    })

    it('get_agent returns application + revisions list', async () => {
        const deps = mkDeps()
        const first = await createRevision(deps, { slug: 'x' })
        await promoteRevision(deps, { rev_id: first.revision_id })
        const out = await getAgent(deps, { slug: 'x' })
        expect(out.revisions).toHaveLength(1)
        expect(out.revisions[0].state).toBe('ready')
    })

    it('get_revision returns spec + file tree', async () => {
        const deps = mkDeps()
        const first = await createRevision(deps, { slug: 'x' })
        const out = await getRevision(deps, { rev_id: first.revision_id })
        expect(out.revision.spec.model).not.toBeUndefined()
        expect(out.files.find((f) => f.path === 'agent.md')).not.toBeUndefined()
    })

    it('update_spec merges patch and re-validates', async () => {
        const deps = mkDeps()
        const first = await createRevision(deps, { slug: 'x' })
        const out = await updateSpec(deps, {
            rev_id: first.revision_id,
            spec_patch: { model: 'claude-sonnet-4-6' },
        })
        expect(out.spec.model).toBe('claude-sonnet-4-6')
    })

    it('write_file of a tool source auto-compiles', async () => {
        const deps = mkDeps()
        const first = await createRevision(deps, { slug: 'x' })
        const SRC = `
            defineTool({
                id: "fetch-acme-account",
                description: "Look up Acme.",
                actions: { default: async () => ({}) },
            })
        `
        const out = await writeFile(deps, {
            rev_id: first.revision_id,
            path: 'tools/fetch-acme-account/source.ts',
            content: SRC,
        })
        expect(out.compiled?.schema_json_path).toBe('tools/fetch-acme-account/schema.json')
        expect(await deps.bundle.exists(first.revision_id, 'tools/fetch-acme-account/compiled.js')).toBe(true)
        expect(await deps.bundle.exists(first.revision_id, 'tools/fetch-acme-account/schema.json')).toBe(true)
        expect(await deps.bundle.exists(first.revision_id, 'tools/fetch-acme-account/inputs.json')).toBe(true)
    })

    it('promote_revision freezes the bundle and stamps sha', async () => {
        const deps = mkDeps()
        const first = await createRevision(deps, { slug: 'x' })
        const out = await promoteRevision(deps, { rev_id: first.revision_id })
        expect(out.bundle_sha256).toMatch(/^[a-f0-9]{64}$/)
        const rev = await deps.revisions.getRevision(first.revision_id)
        expect(rev!.state).toBe('ready')
    })

    it('deploy_revision requires the revision be promoted first', async () => {
        const deps = mkDeps()
        const first = await createRevision(deps, { slug: 'x' })
        await expect(deployRevision(deps, { rev_id: first.revision_id })).rejects.toThrow(/promoted/)
    })

    it('deploy_revision sets live', async () => {
        const deps = mkDeps()
        const first = await createRevision(deps, { slug: 'x' })
        await promoteRevision(deps, { rev_id: first.revision_id })
        await deployRevision(deps, { rev_id: first.revision_id })
        const agent = await getAgent(deps, { slug: 'x' })
        expect(agent.application.live_revision_id).toBe(first.revision_id)
    })

    it('diff_revisions returns two-layer diff', async () => {
        const deps = mkDeps()
        const first = await createRevision(deps, { slug: 'x' })
        await writeFile(deps, { rev_id: first.revision_id, path: 'agent.md', content: 'v1' })
        await promoteRevision(deps, { rev_id: first.revision_id })
        const second = await createRevision(deps, { slug: 'x', parent_revision_id: first.revision_id })
        await writeFile(deps, { rev_id: second.revision_id, path: 'agent.md', content: 'v2' })
        await updateSpec(deps, { rev_id: second.revision_id, spec_patch: { model: 'claude-sonnet-4-6' } })
        const out = await diffRevisions(deps, { a: first.revision_id, b: second.revision_id })
        expect(out.spec.model).not.toBeNull()
        expect(out.files.find((f) => f.path === 'agent.md')?.kind).toBe('modified')
    })

    it('list_files, read_file, delete_file, copy_file round-trip', async () => {
        const deps = mkDeps()
        const first = await createRevision(deps, { slug: 'x' })
        await writeFile(deps, { rev_id: first.revision_id, path: 'skills/foo.md', content: 'x' })
        const files = await listFiles(deps, { rev_id: first.revision_id, prefix: 'skills/' })
        expect(files.files.map((f) => f.path)).toEqual(['skills/foo.md'])
        const r = await readFile(deps, { rev_id: first.revision_id, path: 'skills/foo.md' })
        expect(r.content).toBe('x')
        const second = await createRevision(deps, { slug: 'y' })
        await copyFile(deps, {
            src_rev_id: first.revision_id,
            src_path: 'skills/foo.md',
            dst_rev_id: second.revision_id,
            dst_path: 'skills/foo.md',
        })
        const inSecond = await readFile(deps, { rev_id: second.revision_id, path: 'skills/foo.md' })
        expect(inSecond.content).toBe('x')
        await deleteFile(deps, { rev_id: first.revision_id, path: 'skills/foo.md' })
        expect(await deps.bundle.exists(first.revision_id, 'skills/foo.md')).toBe(false)
    })

    it('archive_agent flips application.archived', async () => {
        const deps = mkDeps()
        await createRevision(deps, { slug: 'x' })
        await archiveAgent(deps, { slug: 'x' })
        expect(await listAgents(deps)).toHaveLength(0)
    })

    it('list_available_tools returns native catalog', async () => {
        const deps = mkDeps()
        const out = await listAvailableTools(deps)
        expect(out.native.map((t) => t.id)).toEqual(expect.arrayContaining(['posthog.query.v1']))
    })
})
