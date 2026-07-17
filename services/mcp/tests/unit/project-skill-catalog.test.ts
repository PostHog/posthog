import { describe, expect, it, vi } from 'vitest'

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

    it('shares one list fetch between descriptions() and listNames()', async () => {
        const request = vi.fn(async () => ({
            count: 1,
            results: [{ name: 'retention-analysis', description: 'Find where users stop returning.' }],
        }))
        const catalog = new ProjectSkillCatalog(makeContext(request))

        const [descriptions, list] = await Promise.all([catalog.descriptions(), catalog.listNames()])

        expect(request).toHaveBeenCalledTimes(1)
        expect(descriptions.get('retention-analysis')).toBe('Find where users stop returning.')
        expect(list.names).toEqual(['retention-analysis'])
    })
    it('falls back to tokenized listing rank when backend search returns nothing', async () => {
        const request = vi.fn(async ({ path }: { path: string }) => {
            if (path.endsWith('/search/')) {
                return { results: [] }
            }
            return {
                count: 2,
                next: null,
                results: [
                    { name: 'hedgebox-revenue-policy', description: 'Qualified enterprise revenue definition.' },
                    { name: 'oncall-runbook', description: 'Paging and escalation.' },
                ],
            }
        })
        const catalog = new ProjectSkillCatalog(makeContext(request))

        const results = await catalog.searchResults('qualified enterprise revenue definition')

        expect(results.map((result) => result.identifier)).toEqual(['project:hedgebox-revenue-policy'])
        expect(results[0]!.score).toBeGreaterThan(0)
    })
})
