import { describe, expect, it, vi } from 'vitest'

import { TasksCreateBody, TasksRunCreateBody } from '@/generated/tasks/api'
import { GENERATED_TOOL_MAP } from '@/tools/generated'
import type { Context } from '@/tools/types'

describe('Generated task tools', () => {
    it('preserves failure details when listing tasks in a space', async () => {
        const latestRun = {
            id: 'run-id',
            status: 'failed',
            error_message: 'Read failed',
            created_at: '2026-01-01T00:00:00Z',
            completed_at: '2026-01-01T00:01:00Z',
        }
        const request = vi.fn().mockResolvedValue({ results: [{ id: 'task-id', latest_run: latestRun }], next: null })
        const context = {
            api: { request, getProjectBaseUrl: () => 'https://example.com/project/42' },
            stateManager: { getProjectId: async () => '42' },
        } as unknown as Context
        const tool = GENERATED_TOOL_MAP['tasks-list']!()
        const params = tool.schema.parse({
            channel: '00000000-0000-4000-8000-000000000001',
            status: 'failed',
            internal: 'all',
            archived: 'all',
        })

        const result = await tool.handler(context, params)

        expect(result).toMatchObject({ results: [{ id: 'task-id', latest_run: latestRun }] })
        expect(request).toHaveBeenCalledWith(
            expect.objectContaining({
                query: expect.objectContaining({ status: 'failed', internal: 'all', archived: 'all' }),
            })
        )
    })

    it('does not expose run inputs on tasks-create', () => {
        const schema = GENERATED_TOOL_MAP['tasks-create']!().schema

        expect(schema.parse({ description: 'Do work', branch: 'main', start_run: true })).toEqual({
            description: 'Do work',
        })
    })

    it('starts a background run with tasks-create-and-run', () => {
        const schema = GENERATED_TOOL_MAP['tasks-create-and-run']!().schema

        expect(schema.parse({ description: 'Do work', branch: 'main', start_run: false })).toEqual({
            description: 'Do work',
            branch: 'main',
            start_run: true,
        })
    })

    it('requires UUIDs for tasks-run-create identifiers', () => {
        const schema = GENERATED_TOOL_MAP['tasks-run-create']!().schema

        expect(() => schema.parse({ id: 'not-a-uuid' })).toThrow()
        expect(() => schema.parse({ id: '00000000-0000-4000-8000-000000000001', resume_from_run_id: 'bad' })).toThrow()
    })

    it('forces tasks-run-create to background mode', () => {
        const schema = GENERATED_TOOL_MAP['tasks-run-create']!().schema

        expect(schema.parse({ id: '00000000-0000-4000-8000-000000000001', mode: 'interactive' })).toMatchObject({
            mode: 'background',
            run_source: 'agent',
        })
    })

    it.each(['tasks-create-and-run', 'tasks-run-create'])(
        '%s sends scheduling options and returns the saved configuration',
        async (name) => {
            const id = '00000000-0000-4000-8000-000000000001'
            const options = {
                scheduled_at: '2026-09-19T12:00:00',
                model: 'gpt-5.3-codex',
                reasoning_effort: 'high',
            }
            const latestRun = { id, status: 'not_started', ...options, scheduled_at: '2026-09-19T12:00:00Z' }
            const request = vi.fn().mockResolvedValue({ id, latest_run: latestRun })
            const context = {
                api: { request, getProjectBaseUrl: () => 'https://example.com/project/42' },
                stateManager: { getProjectId: async () => '42' },
            } as unknown as Context
            const tool = GENERATED_TOOL_MAP[name]!()
            const params = tool.schema.parse({ id, description: 'Check the result', ...options })

            expect(await tool.handler(context, params)).toMatchObject({ latest_run: latestRun })
            expect(request).toHaveBeenCalledWith(expect.objectContaining({ body: expect.objectContaining(options) }))
        }
    )

    it.each(['tasks-create-and-run', 'tasks-run-create'])('%s rejects a run option the API rejects', (name) => {
        const schema = GENERATED_TOOL_MAP[name]!().schema
        const base = { id: '00000000-0000-4000-8000-000000000001', description: 'Check the result' }

        expect(() => schema.parse({ ...base, model: 'gpt-5.3-codex', reasoning_effort: 'very-high' })).toThrow()
        expect(() => schema.parse({ ...base, reasoning_effort: 'high' })).toThrow()
        expect(schema.parse({ ...base, model: 'gpt-5.3-codex', reasoning_effort: 'high' })).toMatchObject({
            model: 'gpt-5.3-codex',
            reasoning_effort: 'high',
        })
    })

    it.each(['2026-09-19T12:00:00Z', '2026-09-19T14:00:00+02:00', '2026-09-19T12:00:00'])(
        'accepts scheduled time %s',
        (scheduled_at) => {
            const schema = GENERATED_TOOL_MAP['tasks-create-and-run']!().schema
            expect(schema.parse({ description: 'Check the result', scheduled_at })).toMatchObject({ scheduled_at })
            expect(TasksCreateBody().parse({ description: 'Check the result', scheduled_at })).toMatchObject({
                scheduled_at,
            })
            expect(TasksRunCreateBody().parse({ scheduled_at })).toMatchObject({ scheduled_at })
            const resume = {
                scheduled_at,
                resume_from_run_id: '00000000-0000-4000-8000-000000000001',
                model: 'claude-sonnet-4-6',
                reasoning_effort: 'medium',
            }
            expect(TasksRunCreateBody().parse(resume)).toMatchObject(resume)
            expect(() => schema.parse({ description: 'Check the result', scheduled_at: 'tomorrow' })).toThrow()
        }
    )
})
