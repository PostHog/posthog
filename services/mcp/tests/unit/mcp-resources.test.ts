import { describe, expect, it } from 'vitest'

import {
    filterResourcesBySelection,
    isResourceUriIncluded,
    parseMcpResources,
    parseMcpResourcesFromConnection,
    resourceCategoryForUri,
} from '@/lib/mcp-resources'
import { parseRequestProperties } from '@/lib/request-properties'

describe('parseMcpResources', () => {
    const cases = [
        { raw: undefined, expected: { policy: 'all' } },
        { raw: null, expected: { policy: 'all' } },
        { raw: '', expected: { policy: 'all' } },
        { raw: '   ', expected: { policy: 'all' } },
        { raw: 'none', expected: { policy: 'none' } },
        { raw: 'NONE', expected: { policy: 'none' } },
        { raw: ' skills ', expected: { policy: 'include', categories: ['skills'] } },
        { raw: 'skills,docs', expected: { policy: 'include', categories: ['skills', 'docs'] } },
        { raw: 'skills,apps,skills', expected: { policy: 'include', categories: ['skills', 'apps'] } },
        { raw: 'banana', expected: { policy: 'all' } },
        { raw: 'skills,banana', expected: { policy: 'include', categories: ['skills'] } },
        { raw: 'none,skills', expected: { policy: 'none' } },
    ] as const

    it.each(cases)('parses $raw', ({ raw, expected }) => {
        expect(parseMcpResources(raw)).toEqual(expected)
    })

    it('parseMcpResourcesFromConnection prefers header over query', () => {
        expect(parseMcpResourcesFromConnection('none', 'skills')).toEqual({ policy: 'none' })
    })

    it('uses header resources before URL resources in parseRequestProperties', () => {
        const request = new Request('https://example.com/mcp?resources=skills', {
            headers: {
                Authorization: 'Bearer phx_test',
                'x-posthog-mcp-resources': 'none',
            },
        })
        expect(parseRequestProperties(request, {}).mcpResources).toEqual({ policy: 'none' })
    })
})

describe('resourceCategoryForUri', () => {
    it('maps known prefixes', () => {
        expect(resourceCategoryForUri('posthog://skills/foo')).toBe('skills')
        expect(resourceCategoryForUri('posthog://docs/bar')).toBe('docs')
        expect(resourceCategoryForUri('ui://posthog/app.html')).toBe('apps')
        expect(resourceCategoryForUri('other://x')).toBeUndefined()
    })
})

describe('isResourceUriIncluded', () => {
    const skillUri = 'posthog://skills/test'
    const docUri = 'posthog://docs/test'
    const appUri = 'ui://posthog/debug.html'

    it('includes everything when policy is all', () => {
        expect(isResourceUriIncluded(skillUri, { policy: 'all' })).toBe(true)
    })

    it('excludes everything when policy is none', () => {
        expect(isResourceUriIncluded(skillUri, { policy: 'none' })).toBe(false)
    })

    it('filters by category list', () => {
        const selection = { policy: 'include' as const, categories: ['skills' as const] }
        expect(isResourceUriIncluded(skillUri, selection)).toBe(true)
        expect(isResourceUriIncluded(docUri, selection)).toBe(false)
        expect(isResourceUriIncluded(appUri, selection)).toBe(false)
    })
})

describe('filterResourcesBySelection', () => {
    const rows = [
        { uri: 'posthog://skills/a', name: 'a' },
        { uri: 'posthog://docs/b', name: 'b' },
        { uri: 'ui://posthog/c.html', name: 'c' },
    ]

    it('returns only skills when requested', () => {
        const filtered = filterResourcesBySelection(rows, { policy: 'include', categories: ['skills'] })
        expect(filtered.map((r) => r.uri)).toEqual(['posthog://skills/a'])
    })
})
