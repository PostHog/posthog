import { describe, expect, it } from 'vitest'
import { z } from 'zod'

import { mergeToolFactories } from '@/tools/mergeToolFactories'
import type { ToolBase, ZodObjectAny } from '@/tools/types'

const factory = (name: string, tag: string): (() => ToolBase<ZodObjectAny>) => {
    return () =>
        ({
            name,
            schema: z.object({}),
            handler: async () => tag,
            _tag: tag,
        }) as ToolBase<ZodObjectAny> & { _tag: string }
}

describe('mergeToolFactories', () => {
    it('lets hand-written factories win on key collision', async () => {
        const generated = {
            'update-feature-flag': factory('update-feature-flag', 'generated'),
            'other-tool': factory('other-tool', 'generated'),
        }
        const handwritten = {
            'update-feature-flag': factory('update-feature-flag', 'handwritten'),
        }

        const merged = mergeToolFactories(generated, handwritten)
        expect(await merged['update-feature-flag']!().handler({} as never, {} as never)).toBe('handwritten')
        expect(await merged['other-tool']!().handler({} as never, {} as never)).toBe('generated')
    })

    it('keeps hand-written keys ahead of generated-only keys', () => {
        // Key order decides the order tools are listed in and which ones the compact
        // domain index is built from, so overriding a tool must not reorder the catalog.
        const generated = {
            'action-create': factory('action-create', 'generated'),
            'update-feature-flag': factory('update-feature-flag', 'generated'),
        }
        const handwritten = {
            'update-feature-flag': factory('update-feature-flag', 'handwritten'),
            'feature-flag-get-definition-by-key': factory('feature-flag-get-definition-by-key', 'handwritten'),
        }

        expect(Object.keys(mergeToolFactories(generated, handwritten))).toEqual([
            'update-feature-flag',
            'feature-flag-get-definition-by-key',
            'action-create',
        ])
    })
})
