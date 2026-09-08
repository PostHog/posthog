import { strToU8, zipSync } from 'fflate'
import { describe, expect, it, vi } from 'vitest'

import type { ProjectSkillCatalog } from '@/skills/project-skill-catalog'
import {
    formatLearnFile,
    LEARN_OUTPUT_CHAR_LIMIT,
    makeSkillFile,
    readLearnLines,
    searchLearnFile,
    SkillCatalog,
} from '@/skills/skill-catalog'
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
                'Find where users stop returning. 日本語のガイド。',
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

function makeProjectSkills(overrides: Partial<Record<string, unknown>> = {}): ProjectSkillCatalog {
    return {
        listNames: vi.fn(async () => ({ count: 1, names: ['team-conventions'], truncated: false })),
        describe: vi.fn(async () => new Map([['team-conventions', 'Team-specific conventions.']])),
        searchResults: vi.fn(async () => []),
        read: vi.fn(async () => 'project skill'),
        searchFile: vi.fn(async () => 'project file match'),
        readLines: vi.fn(async () => 'project lines'),
        ...overrides,
    } as unknown as ProjectSkillCatalog
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

        expect(result).toContain('Files:')
        expect(result).toContain('- SKILL.md (8 lines,')
        expect(result).toContain('- references/functions.md (3 lines,')
        expect(result).toContain('# Retention analysis')
        expect(result).not.toContain('name: retention-analysis')
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

    it('merges PostHog and project search results by relevance and supports Unicode and quoted paths', async () => {
        const projectSkills = makeProjectSkills({
            searchResults: vi.fn(async (query: string) => [
                {
                    identifier: 'project:conversion-playbook',
                    description: 'Team conversion playbook.',
                    snippets: [{ path: 'SKILL.md', line: 4, text: 'Our conversion funnel.' }],
                    // A name match on "conversion" must outrank a PostHog body-only match.
                    score: query.includes('conversion') ? 3300 : 900,
                },
            ]),
        })
        const learn = new ExecLearnCatalog([], { posthog: makeCatalog(), project: projectSkills })

        const listed = JSON.parse(await learn.execute('skills'))
        const ranked = await learn.execute('-s conversion')
        const unicodeResult = await learn.execute('-s 日本語')

        expect(listed.project).toEqual({
            available: true,
            count: 1,
            listed: 1,
            truncated: false,
            skills: ['project:team-conventions'],
        })
        // Regression guard: the name-matching project skill outranks PostHog's `funnels`,
        // which only matches on description/body — the old code always ordered PostHog first.
        expect(ranked.indexOf('## project:conversion-playbook')).toBeLessThan(ranked.indexOf('## posthog:funnels'))
        expect(ranked.indexOf('## posthog:funnels')).toBeGreaterThan(-1)
        expect(unicodeResult).toContain('## posthog:retention-analysis')
        expect(unicodeResult).toContain('## project:conversion-playbook')
        expect(projectSkills.searchResults).toHaveBeenLastCalledWith('日本語')
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

    it.each([
        ['needle\na\nb\nc', '1: needle\n2: a\n3: b'],
        ['a\nb\nc\nneedle', '2: b\n3: c\n4: needle'],
        ['a\nneedle\nneedle\nb\n', '1: a\n2: needle\n3: needle\n4: b\n\n1: a\n2: needle\n3: needle\n4: b\n5: '],
        ['\n\nneedle 日本語 🦔\n', '1: \n2: \n3: needle 日本語 🦔\n4: '],
    ])('preserves line numbers and overlapping search context for %j', (content, context) => {
        const file = makeSkillFile('notes.md', content)
        expect(searchLearnFile('example', file, 'needle')).toBe(`Matches in example/notes.md:\n\n${context}`)
    })

    it('caps file search at 50 matches while including the final match context', () => {
        const file = makeSkillFile(
            'notes.md',
            Array.from({ length: 60 }, (_, index) => `needle ${index}\nbefore\nmiddle\nafter`).join('\n')
        )
        const output = searchLearnFile('example', file, 'needle')
        expect(output.split('\n\n')).toHaveLength(51)
        expect(output).toContain('197: needle 49\n198: before\n199: middle')
        expect(output).not.toContain('needle 50')
    })

    it.each(['# ' + 'x'.repeat(100_000), '# Heading\n'.repeat(10_000)])(
        'bounds oversized outlines and search output for long lines and many headings (%#)',
        (content) => {
            const file = makeSkillFile('notes.md', content)
            const outline = formatLearnFile('example', file)
            expect(outline).toHaveLength(LEARN_OUTPUT_CHAR_LIMIT)
            expect(outline).toContain('[Output truncated.')
            const search = searchLearnFile('example', file, file.lineCount === 1 ? 'x' : 'heading')
            expect(search.length).toBeLessThanOrEqual(LEARN_OUTPUT_CHAR_LIMIT)
            if (file.lineCount === 1) {
                expect(search).toContain('[Output truncated.')
            } else {
                expect(search.split('\n\n')).toHaveLength(51)
            }
        }
    )

    it('reads and searches a newline-heavy file, including its last and empty lines', () => {
        const file = makeSkillFile('notes.md', `x${'\n'.repeat(999_998)}x`)
        expect(file.lineCount).toBe(999_999)
        expect(formatLearnFile('example', file)).toContain('(No Markdown headings found.)')
        expect(searchLearnFile('example', file, 'missing')).toContain('No matches for "missing"')
        expect(readLearnLines('example', file, 999_998, 999_999)).toBe(
            'File: example/notes.md lines 999998:999999\n\n999998: \n999999: x'
        )
        expect(() => readLearnLines('example', file, 1, file.lineCount)).toThrow('Requested line range exceeds')
        expect(() => readLearnLines('example', file, 1, file.lineCount + 1)).toThrow('Invalid line range')
        const empty = makeSkillFile('empty.md', '')
        expect(empty.lineCount).toBe(1)
        expect(readLearnLines('example', empty, 1, 1)).toBe('File: example/empty.md lines 1:1\n\n1: ')
    })

    it('rejects unsafe archive entries before exposing them', () => {
        const archive = makeArchive({
            '../escape/SKILL.md': makeSkill('escape', 'Unsafe archive.', '# Escape'),
        })

        expect(() => SkillCatalog.fromZip(archive)).toThrow('Unsafe skill archive path')
    })

    it.each([
        ['analyzing', 'trends', true], // analyzing → analy ⊂ "analysis"
        ['funnels', 'conversion', true], // funnels → funnel
        ['sessions', 'assessment', false], // min-5 guard: "sessions" must not reach "assessing"
    ])('light stemming links query "%s" to %s content (match=%s)', (query, skill, shouldMatch) => {
        const catalog = SkillCatalog.fromZip(
            makeArchive({
                'trends/SKILL.md': makeSkill(
                    'trends',
                    'Chart product metrics over time.',
                    '# Trends\n\nRun a cohort analysis.'
                ),
                'conversion/SKILL.md': makeSkill(
                    'conversion',
                    'Chart product metrics over time.',
                    '# Conversion\n\nBuild a conversion funnel.'
                ),
                'assessment/SKILL.md': makeSkill(
                    'assessment',
                    'Review internal controls.',
                    '# Assessment\n\nStart by assessing exposure.'
                ),
            })
        )

        if (shouldMatch) {
            expect(catalog.search(query)).toContain(skill)
        } else {
            expect(catalog.search(query)).not.toContain(skill)
        }
    })

    it('excludes SKILL.md frontmatter from snippets while keeping raw line numbers', () => {
        const catalog = SkillCatalog.fromZip(
            makeArchive({
                'cohort-guide/SKILL.md': makeSkill(
                    'cohort-guide',
                    'Analyze retention cohorts.',
                    '# Cohort guide\n\nAnalyze retention cohorts weekly.'
                ),
            })
        )

        const output = catalog.search('retention cohorts')
        // The `description:` frontmatter line (raw line 3) must not surface as a snippet — the
        // description already prints on its own — and the body match keeps its real line number.
        expect(output).not.toContain('description:')
        expect(output).toContain('SKILL.md:8: Analyze retention cohorts weekly.')
    })

    it('exposes descending scores from searchResults', () => {
        const catalog = SkillCatalog.fromZip(
            makeArchive({
                'funnels/SKILL.md': makeSkill(
                    'funnels',
                    'Analyze conversion funnels.',
                    '# Funnels\n\nBuild a conversion funnel.'
                ),
                'trends/SKILL.md': makeSkill(
                    'trends',
                    'Chart metrics over time.',
                    '# Trends\n\nA funnel is not a trend.'
                ),
            })
        )

        const results = catalog.searchResults('funnel')
        expect(results.map((result) => result.identifier)).toEqual(['funnels', 'trends'])
        expect(results[0]!.score!).toBeGreaterThan(results[1]!.score!)
    })

    it('offers a read and line-range recovery hint when a file search finds nothing', () => {
        const output = makeCatalog().searchFile('retention-analysis', 'references/functions.md', 'nonexistentxyz')

        expect(output).toContain('No matches for "nonexistentxyz" in retention-analysis/references/functions.md.')
        expect(output).toContain('Read it with `learn retention-analysis references/functions.md` (3 lines,')
        expect(output).toContain('--lines <start>:<end>')
    })

    it('describes a batch of qualified names, tolerating unknown names without failing the batch', async () => {
        const learn = new ExecLearnCatalog([], { posthog: makeCatalog(), project: makeProjectSkills() })

        const output = await learn.execute('-d posthog:funnels posthog:missing project:team-conventions')

        expect(output).toBe(
            'posthog:funnels: Analyze conversion funnels.\n' +
                '[unknown skill: posthog:missing]\n' +
                'project:team-conventions: Team-specific conventions.'
        )
    })

    it('caps the batch describe at 20 skills', async () => {
        const learn = new ExecLearnCatalog([], { posthog: makeCatalog() })
        const names = Array.from({ length: 21 }, (_, index) => `posthog:s${index}`).join(' ')

        await expect(learn.execute(`-d ${names}`)).rejects.toThrow('at most 20 skills')
    })

    it('reads several skills in one command', async () => {
        const learn = new ExecLearnCatalog([], { posthog: makeCatalog() })

        const output = await learn.execute('posthog:funnels posthog:retention-analysis')

        expect(output).toContain('Skill: posthog:funnels')
        expect(output).toContain('Skill: posthog:retention-analysis')
    })

    it('reads several files of one skill in one command', async () => {
        const learn = new ExecLearnCatalog([], { posthog: makeCatalog() })

        const output = await learn.execute('posthog:retention-analysis SKILL.md references/functions.md')

        expect(output).toContain('File: posthog:retention-analysis/SKILL.md')
        expect(output).toContain('File: posthog:retention-analysis/references/functions.md')
    })

    it('rejects a scoped flag combined with multiple paths', async () => {
        const learn = new ExecLearnCatalog([], { posthog: makeCatalog() })

        await expect(
            learn.execute('posthog:retention-analysis SKILL.md references/functions.md --lines 1:2')
        ).rejects.toThrow('Usage: learn <source>:<skill>')
    })

    it.each([
        [1, true],
        [40, false],
    ])('recovers from a zero-hit search (project count=%i, inline=%s)', async (count, inline) => {
        const projectSkills = makeProjectSkills({
            searchResults: vi.fn(async () => []),
            listNames: vi.fn(async () => ({ count, names: ['team-conventions'], truncated: false })),
        })
        const learn = new ExecLearnCatalog([], { posthog: makeCatalog(), project: projectSkills })

        const output = await learn.execute('-s zzzznomatch')

        expect(output).toContain('No skills matched "zzzznomatch".')
        expect(output).toContain('None of the query words appear in any skill.')
        if (inline) {
            expect(output).toContain('Available skills:')
            expect(output).toContain('posthog: funnels, retention-analysis')
            expect(output).toContain('project: team-conventions')
        } else {
            expect(output).toContain('2 posthog and 40 project skills exist')
            expect(output).toContain('learn skills')
        }
    })
    describe('skill invocation reporting', () => {
        it('reports successful loads with source, path, and read kind — never searches or describes', async () => {
            const invocations: unknown[] = []
            const learn = new ExecLearnCatalog([], { posthog: makeCatalog(), project: makeProjectSkills() }, (inv) =>
                invocations.push(inv)
            )

            await learn.execute('posthog:retention-analysis')
            await learn.execute('posthog:retention-analysis references/functions.md')
            await learn.execute('project:team-conventions notes.md --lines 1:5')
            await learn.execute('-s retention')
            await learn.execute('-d posthog:funnels')
            await learn.execute('skills')

            expect(invocations).toEqual([
                { source: 'posthog', skill: 'retention-analysis', path: undefined, readKind: 'skill' },
                { source: 'posthog', skill: 'retention-analysis', path: 'references/functions.md', readKind: 'file' },
                { source: 'project', skill: 'team-conventions', path: 'notes.md', readKind: 'file_lines' },
            ])
        })

        it('reports one invocation per file in a successful multi-file batch', async () => {
            const invocations: unknown[] = []
            const learn = new ExecLearnCatalog([], { posthog: makeCatalog() }, (inv) => invocations.push(inv))

            await learn.execute('posthog:retention-analysis references/functions.md scripts/run.ts')

            expect(invocations).toEqual([
                { source: 'posthog', skill: 'retention-analysis', path: 'references/functions.md', readKind: 'file' },
                { source: 'posthog', skill: 'retention-analysis', path: 'scripts/run.ts', readKind: 'file' },
            ])
        })

        it('fires no invocations when a file batch fails on one path', async () => {
            const invocations: unknown[] = []
            const learn = new ExecLearnCatalog([], { posthog: makeCatalog() }, (inv) => invocations.push(inv))

            // The command returns no content, so a successful sibling must not report.
            await expect(
                learn.execute('posthog:retention-analysis references/functions.md missing.md')
            ).rejects.toThrow('missing.md')
            expect(invocations).toEqual([])
        })

        it('fires no invocations when a multi-skill batch fails on one skill', async () => {
            const invocations: unknown[] = []
            const learn = new ExecLearnCatalog([], { posthog: makeCatalog() }, (inv) => invocations.push(inv))

            await expect(learn.execute('posthog:retention-analysis posthog:missing')).rejects.toThrow(
                'Unknown skill: "missing"'
            )
            expect(invocations).toEqual([])
        })

        it('keeps learn working when the listener throws', async () => {
            const learn = new ExecLearnCatalog([], { posthog: makeCatalog() }, () => {
                throw new Error('capture failed')
            })

            await expect(learn.execute('posthog:funnels')).resolves.toContain('Build a conversion funnel.')
        })
    })
})
