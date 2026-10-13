import { describe, expect, it } from 'vitest'

import logsPatternsHooks, { DEFAULT_PATTERNS_LIMIT } from '@/tools/logs/logsPatternsHooks'
import type { Context } from '@/tools/types'

const context = {} as Context

describe('logsPatternsHooks.beforeRequest', () => {
    it.each([
        { name: 'no limit', query: { serviceNames: ['api'] }, limit: DEFAULT_PATTERNS_LIMIT },
        { name: 'a null limit', query: { serviceNames: ['api'], limit: null }, limit: DEFAULT_PATTERNS_LIMIT },
        { name: 'an explicit limit', query: { serviceNames: ['api'], limit: 200 }, limit: 200 },
    ])('sends the right limit for $name', async ({ query, limit }) => {
        const params = await logsPatternsHooks.beforeRequest(context, { query })

        expect(params.query).toEqual({ serviceNames: ['api'], limit })
    })
})
