import { describe, expect, it } from 'vitest'
import { z } from 'zod'

import { TOOL_MAP } from '@/tools'
import { GENERATED_TOOL_MAP } from '@/tools/generated'
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

        const merged = mergeToolFactories({ generated, handwritten })
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

        expect(Object.keys(mergeToolFactories({ generated, handwritten }))).toEqual([
            'update-feature-flag',
            'feature-flag-get-definition-by-key',
            'action-create',
        ])
    })

    describe('param casing', () => {
        const merged = mergeToolFactories({ generated: GENERATED_TOOL_MAP, handwritten: TOOL_MAP })
        const schemaOf = (name: string): z.ZodType => merged[name]!().schema

        it.each([
            ['query-error-tracking-issue', { issue_id: 'issue-1' }, 'issueId', 'issue_id'],
            ['switch-project', { project_id: 2 }, 'projectId', 'project_id'],
            ['code-review-approvals-runs-create', { repository: 'o/r', prNumber: 7 }, 'pr_number', 'prNumber'],
        ])('%s accepts the other casing of a param', (name, input, canonical, alias) => {
            const result = schemaOf(name).safeParse(input)
            expect(result.success).toBe(true)
            const data = result.data as Record<string, unknown>
            expect(data[canonical]).toEqual((input as Record<string, unknown>)[alias])
            expect(data).not.toHaveProperty(alias)
        })

        it('keeps the declared name when a call sends both casings', () => {
            const result = schemaOf('query-error-tracking-issue').safeParse({ issueId: 'declared', issue_id: 'alias' })
            expect((result.data as Record<string, unknown>).issueId).toBe('declared')
        })

        it('does not change the advertised schema', () => {
            const advertised = z.toJSONSchema(schemaOf('query-error-tracking-issue'), { io: 'input' })
            const original = z.toJSONSchema(GENERATED_TOOL_MAP['query-error-tracking-issue']!().schema, {
                io: 'input',
            })
            expect(advertised).toEqual(original)
        })
    })
})
