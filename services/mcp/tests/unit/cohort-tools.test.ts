import { describe, expect, it, vi } from 'vitest'
import { z } from 'zod'

import { GENERATED_TOOL_MAP } from '@/tools/generated'
import { getToolDefinition } from '@/tools/toolDefinitions'
import type { Context } from '@/tools/types'

function createMockContext(requestMock: ReturnType<typeof vi.fn>): Context {
    return {
        api: {
            request: requestMock,
            getProjectBaseUrl: () => 'https://app.posthog.com/project/17',
        },
        stateManager: { getProjectId: vi.fn().mockResolvedValue('17') },
    } as unknown as Context
}

function inputKeys(name: string): string[] {
    const tool = GENERATED_TOOL_MAP[name]?.()
    expect(tool, `${name} is missing from the generated tool map`).not.toBeUndefined()
    const schema = z.toJSONSchema(tool!.schema, { io: 'input', reused: 'inline' }) as {
        properties?: Record<string, unknown>
    }
    return Object.keys(schema.properties ?? {})
}

describe('cohort tools', () => {
    it('cohorts-delete takes only the cohort id and is marked destructive', () => {
        expect(inputKeys('cohorts-delete')).toEqual(['id'])

        const definition = getToolDefinition('cohorts-delete')
        expect(definition.required_scopes).toEqual(['cohort:write'])
        expect(definition.annotations?.readOnlyHint).toBe(false)
        expect(definition.annotations?.destructiveHint).toBe(true)
    })

    // The cohorts API forbids DELETE, so a hard delete would fail on every call.
    it('cohorts-delete soft-deletes the cohort', async () => {
        const requestMock = vi.fn().mockResolvedValue({ id: 42, deleted: true })

        await GENERATED_TOOL_MAP['cohorts-delete']!().handler(createMockContext(requestMock), { id: 42 })

        expect(requestMock).toHaveBeenCalledExactlyOnceWith({
            method: 'PATCH',
            path: '/api/projects/17/cohorts/42/',
            body: { deleted: true },
        })
    })

    // Deletes must go through the tool that clients ask the user to confirm.
    it('cohorts-partial-update cannot delete a cohort', () => {
        expect(inputKeys('cohorts-partial-update')).not.toContain('deleted')
        expect(getToolDefinition('cohorts-partial-update').annotations?.destructiveHint).toBe(false)
    })
})
