import { describe, expect, it, vi } from 'vitest'

import { PostHogApiError } from '@/lib/errors'
import { ProjectSkillCatalog } from '@/skills/project-skill-catalog'
import type { Context } from '@/tools/types'

type RequestFn = (args: { method: string; path: string; query?: unknown }) => Promise<unknown>

function makeContext(request: RequestFn): Context {
    return {
        api: { request },
        stateManager: { getProjectId: vi.fn().mockResolvedValue(12) },
    } as unknown as Context
}

const SKILL_BODY = '# Retention\nHow to analyze retention.'
const SKILL_PAYLOAD = {
    body: SKILL_BODY,
    description: 'Find where users stop returning.',
    files: [],
    version: 7,
    body_total_length: SKILL_BODY.length,
    body_next_offset: null,
}

describe('ProjectSkillCatalog', () => {
    it.each([
        { lineCount: 600, expectedRead: 'TAILMARKER: compare like cohorts.' },
        { lineCount: 1800, expectedRead: 'too large to return in full' },
    ])(
        'fetches the complete body in one request before formatting $lineCount lines',
        async ({ lineCount, expectedRead }) => {
            const body =
                '# 🦔 Retention\n' +
                'Keep cohort definitions stable.\n'.repeat(lineCount) +
                'TAILMARKER: compare like cohorts.'
            const request = vi.fn<RequestFn>(async ({ query }) => {
                const params = query as { body_length?: number } | undefined
                const length = params?.body_length ?? 8000
                const characters = Array.from(body)
                return {
                    ...SKILL_PAYLOAD,
                    body: characters.slice(0, length).join(''),
                    body_total_length: characters.length,
                    body_next_offset: length < characters.length ? length : null,
                }
            })
            const catalog = new ProjectSkillCatalog(makeContext(request))

            const read = await catalog.read('retention-analysis')
            const search = await catalog.searchFile('retention-analysis', 'SKILL.md', 'TAILMARKER')
            const lines = await catalog.readLines('retention-analysis', 'SKILL.md', lineCount + 2, lineCount + 2)

            expect(read).toContain(`${body.length} chars`)
            expect(read).toContain(expectedRead)
            expect(search).toContain('TAILMARKER: compare like cohorts.')
            expect(lines).toContain('TAILMARKER: compare like cohorts.')
            expect(request).toHaveBeenCalledTimes(1)
        }
    )

    it('memoizes a skill fetch so repeated reads make one request', async () => {
        const request = vi.fn(async () => SKILL_PAYLOAD)
        const catalog = new ProjectSkillCatalog(makeContext(request))

        await catalog.read('retention-analysis')
        await catalog.read('retention-analysis')

        expect(request).toHaveBeenCalledTimes(1)
    })

    it('dedupes concurrent file reads by memoizing the in-flight promise', async () => {
        const request = vi.fn(async ({ path }: { path: string }) => {
            if (path.includes('/files/')) {
                return { path: 'reference.md', content: 'body', content_type: 'text/markdown' }
            }
            return SKILL_PAYLOAD
        })
        const catalog = new ProjectSkillCatalog(makeContext(request))

        // Both calls start before either resolves — only a promise-level memo dedupes this.
        await Promise.all([
            catalog.read('retention-analysis', 'reference.md'),
            catalog.read('retention-analysis', 'reference.md'),
        ])

        expect(request).toHaveBeenCalledTimes(1)
    })

    it('retries after a rejection because the failed memo entry is evicted', async () => {
        let calls = 0
        const request = vi.fn(async () => {
            calls += 1
            if (calls === 1) {
                throw new Error('transient')
            }
            return SKILL_PAYLOAD
        })
        const catalog = new ProjectSkillCatalog(makeContext(request))

        await expect(catalog.read('retention-analysis')).rejects.toThrow('transient')
        await catalog.read('retention-analysis')

        expect(request).toHaveBeenCalledTimes(2)
    })

    it.each(['a', '🦔'])('reads the tail of a body at the byte limit with %s characters', async (character) => {
        const tail = '\nTAILMARKER: compare like cohorts.'
        const remainingBytes = 1_000_000 - new TextEncoder().encode(tail).length
        const characterBytes = new TextEncoder().encode(character).length
        const body =
            character.repeat(Math.floor(remainingBytes / characterBytes)) +
            ' '.repeat(remainingBytes % characterBytes) +
            tail
        const request = vi.fn(async () => ({
            ...SKILL_PAYLOAD,
            body,
            body_total_length: Array.from(body).length,
        }))
        const catalog = new ProjectSkillCatalog(makeContext(request))

        expect(await catalog.readLines('retention-analysis', 'SKILL.md', 2, 2)).toContain(tail.trim())
    })

    it.each([
        {
            label: 'ASCII over the byte limit',
            body: 'a'.repeat(1_000_001),
            nextOffset: null,
            totalLength: 1_000_001,
            error: 'exceeds the 1 MB limit',
        },
        {
            label: 'Unicode over the byte limit',
            body: '🦔'.repeat(250_001),
            nextOffset: null,
            totalLength: 250_001,
            error: 'exceeds the 1 MB limit',
        },
        {
            label: 'a continuation offset',
            body: 'First page',
            nextOffset: 10,
            totalLength: 20,
            error: 'incomplete skill body',
        },
        {
            label: 'a missing tail without a continuation offset',
            body: 'First page',
            nextOffset: null,
            totalLength: 20,
            error: 'incomplete skill body',
        },
    ])('rejects $label without caching a partial skill', async ({ body, nextOffset, totalLength, error }) => {
        const request = vi
            .fn()
            .mockResolvedValueOnce({
                ...SKILL_PAYLOAD,
                body,
                body_next_offset: nextOffset,
                body_total_length: totalLength,
            })
            .mockResolvedValueOnce(SKILL_PAYLOAD)
        const catalog = new ProjectSkillCatalog(makeContext(request))

        await expect(catalog.read('retention-analysis')).rejects.toThrow(error)
        expect(await catalog.read('retention-analysis')).toContain(SKILL_BODY)
        expect(request).toHaveBeenCalledTimes(2)
    })

    it('shares one list fetch between describe() and listNames()', async () => {
        const request = vi.fn(async () => ({
            count: 1,
            results: [{ name: 'retention-analysis', description: 'Find where users stop returning.' }],
        }))
        const catalog = new ProjectSkillCatalog(makeContext(request))

        const [descriptions, list] = await Promise.all([catalog.describe(['retention-analysis']), catalog.listNames()])

        expect(request).toHaveBeenCalledTimes(1)
        expect(descriptions.get('retention-analysis')).toBe('Find where users stop returning.')
        expect(list.names).toEqual(['retention-analysis'])
    })

    // A truncated listing (>PROJECT_SKILL_LIST_LIMIT) omits skills sorting past the cap; without the
    // exact-name fallback `learn -d` misreports a real skill as unknown.
    it.each([
        ['resolves a real skill past the list cap', 'deep-skill', 'Past the list cap.'],
        ['omits a genuinely unknown name so it renders unknown', 'ghost-skill', undefined],
    ])('describe on a truncated listing %s', async (_label, name, expected) => {
        const request = vi.fn(async ({ path, query }: { path: string; query?: any }) => {
            if (path.endsWith('/llm_skills/')) {
                // 500 skills exist but only the first page is returned → truncated listing.
                return query.offset === 0
                    ? { count: 500, results: [{ name: 'listed-skill', description: 'In the listing.' }] }
                    : { count: 500, results: [] }
            }
            if (path.includes('/llm_skills/name/')) {
                if (path.includes('deep-skill')) {
                    return { ...SKILL_PAYLOAD, name: 'deep-skill', description: 'Past the list cap.' }
                }
                throw new PostHogApiError({ status: 404, statusText: 'Not Found', body: '', url: path, method: 'GET' })
            }
            throw new Error(`unexpected request: ${path}`)
        })
        const catalog = new ProjectSkillCatalog(makeContext(request))

        const descriptions = await catalog.describe([name])

        expect(descriptions.get(name)).toBe(expected)
    })

    it('describe makes no exact-name fetch when the listing is complete', async () => {
        const request = vi.fn(async ({ path }: { path: string }) => {
            if (path.endsWith('/llm_skills/')) {
                return { count: 1, results: [{ name: 'listed-skill', description: 'In the listing.' }] }
            }
            throw new Error(`unexpected request: ${path}`)
        })
        const catalog = new ProjectSkillCatalog(makeContext(request))

        const descriptions = await catalog.describe(['listed-skill', 'missing-skill'])

        expect(descriptions.get('listed-skill')).toBe('In the listing.')
        // Complete listing → a miss is authoritative; no exact-name endpoint round-trip.
        expect(descriptions.has('missing-skill')).toBe(false)
        expect(request).toHaveBeenCalledTimes(1)
    })

    it('surfaces a body-only match via per-token search when the whole query misses', async () => {
        const request = vi.fn(async ({ path, query }: { path: string; query?: any }) => {
            if (path.endsWith('/search/')) {
                // Whole multi-word query misses; a single informative token hits on body content.
                if (query.query === 'revenue') {
                    return {
                        results: [
                            {
                                name: 'billing-internals',
                                description: 'Unrelated title.',
                                matches: [
                                    {
                                        matched_field: 'body',
                                        path: 'SKILL.md',
                                        line: 12,
                                        excerpt: 'revenue recognition rules',
                                    },
                                ],
                            },
                        ],
                    }
                }
                return { results: [] }
            }
            // Listing has no matching name/description, so only the body match can surface this skill.
            return { count: 1, results: [{ name: 'billing-internals', description: 'Unrelated title.' }] }
        })
        const catalog = new ProjectSkillCatalog(makeContext(request))

        const results = await catalog.searchResults('where is revenue recognized')

        expect(results.map((result) => result.identifier)).toEqual(['project:billing-internals'])
        expect(results[0]!.snippets).toContainEqual({ path: 'SKILL.md', line: 12, text: 'revenue recognition rules' })
        expect(results[0]!.score).toBeGreaterThan(0)
    })

    it('degrades to the listing rank when every per-token search fails', async () => {
        const request = vi.fn(async ({ path, query }: { path: string; query?: any }) => {
            if (path.endsWith('/search/')) {
                if (query.query === 'retention analysis guide') {
                    return { results: [] } // whole-query miss
                }
                throw new Error('token search failed') // a failing per-token search must not sink the fallback
            }
            return { count: 1, results: [{ name: 'retention-analysis', description: 'Analyze retention cohorts.' }] }
        })
        const catalog = new ProjectSkillCatalog(makeContext(request))

        const results = await catalog.searchResults('retention analysis guide')

        expect(results.map((result) => result.identifier)).toEqual(['project:retention-analysis'])
        expect(results[0]!.score).toBeGreaterThan(0)
    })
})
