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

const SKILL_PAYLOAD = {
    body: '# Retention\nHow to analyze retention.',
    description: 'Find where users stop returning.',
    files: [],
}

describe('ProjectSkillCatalog', () => {
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
                    return { name: 'deep-skill', body: '', description: 'Past the list cap.', files: [] }
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
