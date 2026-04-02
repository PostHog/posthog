import { describe, expect, it } from 'vitest'
import { z } from 'zod'

import { createQueryWrapper } from '@/tools/query-wrapper-factory'

describe('createQueryWrapper _meta', () => {
    const schema = z.object({ kind: z.string() })

    it('sets responseFormat in _meta when provided', () => {
        const factory = createQueryWrapper({ name: 'test', schema, kind: 'TestQuery', responseFormat: 'json' })
        const tool = factory()
        expect(tool._meta?.responseFormat).toBe('json')
    })

    it('omits responseFormat from _meta when not provided', () => {
        const factory = createQueryWrapper({ name: 'test', schema, kind: 'TestQuery' })
        const tool = factory()
        expect(tool._meta?.responseFormat).toBeUndefined()
    })

    it('sets both uiResourceUri and responseFormat in _meta', () => {
        const factory = createQueryWrapper({
            name: 'test',
            schema,
            kind: 'TestQuery',
            uiResourceUri: 'ui://posthog/test.html',
            responseFormat: 'json',
        })
        const tool = factory()
        expect(tool._meta).toEqual({
            ui: { resourceUri: 'ui://posthog/test.html' },
            responseFormat: 'json',
        })
    })
})
