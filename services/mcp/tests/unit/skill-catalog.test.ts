import { strToU8, zipSync } from 'fflate'
import { describe, expect, it, vi } from 'vitest'

import type { ProjectSkillCatalog } from '@/skills/project-skill-catalog'
import { LEARN_OUTPUT_CHAR_LIMIT, SkillCatalog } from '@/skills/skill-catalog'
import { ExecLearnCatalog } from '@/tools/exec-learn'

function makeArchive(files: Record<string, string>): Uint8Array {
    return zipSync(Object.fromEntries(Object.entries(files).map(([path, content]) => [path, strToU8(content)])))
}

function makeSkill(name: string, description: string, body: string): string {
    return `---\nname: ${name}\ndescription: ${description}\n---\n\n${body}`
}

function makeCatalog(): SkillCatalog {
    return SkillCatalog.fromZip(
        makeArchive({
            'retention-analysis/SKILL.md': makeSkill(
                'retention-analysis',
                'Find where users stop returning.',
                '# Retention analysis\n\nQuery weekly retention cohorts.'
            ),
            'retention-analysis/references/functions.md':
                '# Available functions\n\nUse retention cohorts with dateDiff.',
            'retention-analysis/scripts/run.ts': 'const privateSearchToken = "unindexed-token"',
            'funnels/SKILL.md': makeSkill(
                'funnels',
                'Analyze conversion funnels.',
                '# Funnels\n\nBuild a conversion funnel.'
            ),
        })
    )
}

describe('SkillCatalog and exec learn', () => {
    it('lists qualified names without descriptions and ranks full-text matches deterministically', async () => {
        const catalog = makeCatalog()
        const learn = new ExecLearnCatalog([], { posthog: catalog })

        expect(JSON.parse(await learn.execute('skills'))).toEqual({
            posthog: {
                available: true,
                count: 2,
                listed: 2,
                truncated: false,
                skills: ['posthog:funnels', 'posthog:retention-analysis'],
            },
            project: {
                available: false,
                reason: 'Project skills are temporarily unavailable.',
            },
        })
        const result = await learn.execute('-s weekly retention')
        expect(result).toContain('## posthog:retention-analysis')
        expect(result).toContain('SKILL.md:8: Query weekly retention cohorts.')
        expect(result).toContain('[Project skills unavailable: Project skills are temporarily unavailable.]')
        await expect(learn.execute('project:team-skill')).rejects.toThrow('Project skills are temporarily unavailable')
    })

    it('indexes every file path and Markdown content but not script contents', () => {
        const catalog = makeCatalog()

        expect(catalog.search('functions.md')).toContain('retention-analysis')
        expect(catalog.search('dateDiff')).toContain('retention-analysis')
        expect(catalog.search('run.ts')).toContain('retention-analysis')
        expect(catalog.search('unindexed-token')).toBe('No skills matched "unindexed-token".')
        expect(() => catalog.searchFile('retention-analysis', 'scripts/run.ts', 'const')).toThrow(
            'Only Markdown contents are searchable'
        )
    })

    it('returns the rendered skill with a manifest and supports scoped reads', async () => {
        const catalog = makeCatalog()
        const learn = new ExecLearnCatalog([], { posthog: catalog })
        const result = catalog.read('retention-analysis')

        expect(result).toContain('## Files')
        expect(result).toContain('- SKILL.md (8 lines,')
        expect(result).toContain('- references/functions.md (3 lines,')
        expect(catalog.searchFile('retention-analysis', 'references/functions.md', 'dateDiff')).toContain(
            '3: Use retention cohorts with dateDiff.'
        )
        expect(catalog.readLines('retention-analysis', 'references/functions.md', 1, 2)).toContain(
            '1: # Available functions\n2:'
        )
        expect(await learn.execute('posthog:retention-analysis references/functions.md -s dateDiff')).toContain(
            '3: Use retention cohorts with dateDiff.'
        )
        expect(await learn.execute('posthog:retention-analysis references/functions.md --lines 1:2')).toContain(
            '1: # Available functions\n2:'
        )
    })

    it('merges PostHog and project search results and supports quoted project paths', async () => {
        const projectSkills = {
            listNames: vi.fn(async () => ({ count: 1, names: ['team-conventions'], truncated: false })),
            searchResults: vi.fn(async () => [
                {
                    identifier: 'project:team-conventions',
                    description: 'Team-specific retention guidance.',
                    snippets: [{ path: 'SKILL.md', line: 4, text: 'Use weekly retention.' }],
                },
            ]),
            read: vi.fn(async () => 'project skill'),
            searchFile: vi.fn(async () => 'project file match'),
            readLines: vi.fn(async () => 'project lines'),
        } as unknown as ProjectSkillCatalog
        const learn = new ExecLearnCatalog([], { posthog: makeCatalog(), project: projectSkills })

        const listed = JSON.parse(await learn.execute('skills'))
        const result = await learn.execute('-s retention')

        expect(listed.project).toEqual({
            available: true,
            count: 1,
            listed: 1,
            truncated: false,
            skills: ['project:team-conventions'],
        })
        expect(result.indexOf('## posthog:retention-analysis')).toBeLessThan(
            result.indexOf('## project:team-conventions')
        )
        await expect(
            learn.execute('project:team-conventions "references/team guide.md" -s weekly retention')
        ).resolves.toBe('project file match')
        expect(projectSkills.searchFile).toHaveBeenCalledWith(
            'team-conventions',
            'references/team guide.md',
            'weekly retention'
        )
    })

    it('returns an outline for an oversized reference and rejects unsafe paths', () => {
        const largeBody = `# Function catalog\n\n${'function signature details\n'.repeat(2_000)}\n## Examples\n`
        const catalog = SkillCatalog.fromZip(
            makeArchive({
                'querying-data/SKILL.md': makeSkill('querying-data', 'Query product data.', '# Querying data'),
                'querying-data/references/functions.md': largeBody,
            })
        )

        const result = catalog.read('querying-data', 'references/functions.md')
        expect(result.length).toBeLessThanOrEqual(LEARN_OUTPUT_CHAR_LIMIT)
        expect(result).toContain('This file is too large to return in full.')
        expect(result).toContain('1: # Function catalog')
        expect(result).toContain('2004: ## Examples')
        expect(() => catalog.read('querying-data', '../SKILL.md')).toThrow('Unsafe skill path')
    })

    it('rejects unsafe archive entries before exposing them', () => {
        const archive = makeArchive({
            '../escape/SKILL.md': makeSkill('escape', 'Unsafe archive.', '# Escape'),
        })

        expect(() => SkillCatalog.fromZip(archive)).toThrow('Unsafe skill archive path')
    })
})
