import { zipSync, strToU8 } from 'fflate'
import * as fs from 'node:fs/promises'
import * as os from 'node:os'
import * as path from 'node:path'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import type { ContextMillResource } from '@/resources/manifest-types'

vi.mock('@/resources/internals', () => ({
    fetchContextMillResources: vi.fn(),
    filterValidEntries: vi.fn((entries: ContextMillResource[]) => entries),
    loadManifestFromArchive: vi.fn(),
}))

import { installSkill } from '@/cli/skills'
import { fetchContextMillResources, loadManifestFromArchive } from '@/resources/internals'

const skillZip = zipSync({
    'SKILL.md': strToU8('# Test skill\n'),
})

function skillEntry(id: string): ContextMillResource {
    return {
        id,
        name: 'Test skill',
        uri: `context-mill://skills/${id}`,
        file: 'test-skill.zip',
        resource: {
            mimeType: 'text/markdown',
            description: 'A test skill',
            text: '# Test skill',
        },
    }
}

function mockSkillArchive(entries: ContextMillResource[]): void {
    vi.mocked(fetchContextMillResources).mockResolvedValue({ 'test-skill.zip': skillZip })
    vi.mocked(loadManifestFromArchive).mockReturnValue({ version: '1', resources: entries })
}

describe('CLI skill installer', () => {
    beforeEach(() => {
        vi.mocked(fetchContextMillResources).mockReset()
        vi.mocked(loadManifestFromArchive).mockReset()
    })

    it('installs a skill under .agents/skills', async () => {
        const dir = await fs.mkdtemp(path.join(os.tmpdir(), 'posthog-cli-skills-'))
        mockSkillArchive([skillEntry('test-skill')])

        const result = await installSkill('test-skill', { cwd: dir })

        expect(result).toEqual({
            id: 'test-skill',
            directory: path.join(dir, '.agents', 'skills', 'test-skill'),
            fileCount: 1,
        })
        await expect(fs.readFile(path.join(result.directory, 'SKILL.md'), 'utf-8')).resolves.toBe('# Test skill\n')
    })

    it('rejects skill IDs that escape .agents/skills', async () => {
        const dir = await fs.mkdtemp(path.join(os.tmpdir(), 'posthog-cli-skills-'))
        mockSkillArchive([skillEntry('../../../outside')])

        await expect(installSkill('../../../outside', { cwd: dir, force: true })).rejects.toThrow('Invalid skill ID')
        await expect(fs.access(path.join(dir, 'outside'))).rejects.toMatchObject({ code: 'ENOENT' })
    })
})
