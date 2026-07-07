/**
 * Tests for the generated `experiment-copy-to-project` tool.
 *
 * This tool POSTs to the experiments `copy_to_project` action, which copies an
 * experiment into a different project in the same organization. The MCP layer
 * adds two narrow string→int casts (`id` path param + `target_team_id` body
 * param, both routinely passed stringified by agents) and forwards the body.
 * These tests pin the schema shape, both casts, and the request the handler
 * builds — drift the backend can't catch (its tests post raw dicts).
 */
import { describe, expect, it, vi } from 'vitest'
import { z } from 'zod'

import { GENERATED_TOOLS } from '@/tools/generated/experiments'
import type { Context, ToolBase, ZodObjectAny } from '@/tools/types'

const PROJECT_ID = '2'

function getTool(): ToolBase<ZodObjectAny> {
    return (GENERATED_TOOLS['experiment-copy-to-project'] as () => ToolBase<ZodObjectAny>)()
}

function getSchema(): z.ZodTypeAny {
    return getTool().schema as z.ZodTypeAny
}

function parseWith(input: unknown): Record<string, unknown> {
    return getSchema().parse(input) as Record<string, unknown>
}

function createMockContext(requestMock: ReturnType<typeof vi.fn>): Context {
    return {
        api: { request: requestMock } as any,
        stateManager: { getProjectId: vi.fn().mockResolvedValue(PROJECT_ID) } as any,
        env: {} as any,
        sessionManager: {} as any,
        cache: {} as any,
        getDistinctId: async () => 'test-distinct-id',
        trackEvent: async () => {},
    }
}

describe('experiment-copy-to-project', () => {
    it('is registered under the expected tool name', () => {
        expect(getTool().name).toBe('experiment-copy-to-project')
    })

    describe('schema', () => {
        it('requires target_team_id', () => {
            expect(() => getSchema().parse({ id: 1, project_id: PROJECT_ID })).toThrow()
        })

        it('accepts a minimal input with only id + target_team_id', () => {
            const parsed = parseWith({ id: 1, target_team_id: 5, project_id: PROJECT_ID })
            expect(parsed.target_team_id).toBe(5)
            // optional fields are absent, not coerced to undefined values
            expect(parsed).not.toHaveProperty('feature_flag_key')
            expect(parsed).not.toHaveProperty('name')
        })

        it('accepts optional feature_flag_key and name', () => {
            const parsed = parseWith({
                id: 1,
                target_team_id: 5,
                project_id: PROJECT_ID,
                feature_flag_key: 'my-flag',
                name: 'My copy',
            })
            expect(parsed.feature_flag_key).toBe('my-flag')
            expect(parsed.name).toBe('My copy')
        })
    })

    describe('casts', () => {
        it('casts a stringified id', () => {
            const parsed = parseWith({ id: '123', target_team_id: 5, project_id: PROJECT_ID })
            expect(parsed.id).toBe(123)
            expect(typeof parsed.id).toBe('number')
        })

        it('casts a stringified target_team_id', () => {
            const parsed = parseWith({ id: 1, target_team_id: '42', project_id: PROJECT_ID })
            expect(parsed.target_team_id).toBe(42)
            expect(typeof parsed.target_team_id).toBe('number')
        })

        it.each([
            ['boolean true', true],
            ['null', null],
            ['empty string', ''],
            ['decimal string', '1.5'],
            ['non-numeric string', 'abc'],
        ] as const)('rejects unsafe target_team_id: %s', (_label, bad) => {
            expect(() => getSchema().parse({ id: 1, target_team_id: bad, project_id: PROJECT_ID })).toThrow()
        })
    })

    describe('handler', () => {
        it('POSTs to the copy_to_project action with the cast ids and body fields', async () => {
            const requestMock = vi.fn().mockResolvedValue({ id: 999, name: 'My copy' })
            const context = createMockContext(requestMock)

            await getTool().handler(
                context,
                parseWith({
                    id: '123',
                    target_team_id: '42',
                    project_id: PROJECT_ID,
                    feature_flag_key: 'my-flag',
                    name: 'My copy',
                })
            )

            expect(requestMock).toHaveBeenCalledWith({
                method: 'POST',
                path: '/api/projects/2/experiments/123/copy_to_project/',
                body: {
                    target_team_id: 42,
                    feature_flag_key: 'my-flag',
                    name: 'My copy',
                },
            })
        })

        it('omits feature_flag_key and name from the body when not provided', async () => {
            const requestMock = vi.fn().mockResolvedValue({ id: 999 })
            const context = createMockContext(requestMock)

            await getTool().handler(context, parseWith({ id: 1, target_team_id: 5, project_id: PROJECT_ID }))

            const body = requestMock.mock.calls[0]![0].body
            expect(body).toEqual({ target_team_id: 5 })
            expect(body).not.toHaveProperty('feature_flag_key')
            expect(body).not.toHaveProperty('name')
        })
    })
})
