import { describe, expect, it, vi } from 'vitest'
import { z } from 'zod'

import { getToolByName } from '@/shared/test-utils'
import { GENERATED_TOOLS } from '@/tools/generated/tasks'
import type { Context } from '@/tools/types'

function createContext(): { context: Context; request: ReturnType<typeof vi.fn> } {
    const request = vi.fn().mockResolvedValue(undefined)
    const context = {
        api: { request },
        stateManager: { getProjectId: vi.fn().mockResolvedValue('17') },
    } as unknown as Context

    return { context, request }
}

describe('Generated task orchestration tools', () => {
    const tool = getToolByName(GENERATED_TOOLS, 'tasks-notify-parent')

    it('accepts only a non-empty message', () => {
        expect(Object.keys((tool.schema as z.ZodObject).shape)).toEqual(['message'])
        expect(tool.schema.parse({ message: 'Progress update' })).toEqual({ message: 'Progress update' })
        expect(() => tool.schema.parse({ message: '' })).toThrow()
        expect(() => tool.schema.parse({ message: '   ' })).toThrow()
    })

    it('routes the message to the parent endpoint', async () => {
        const { context, request } = createContext()

        await tool.handler(context, { message: 'Need clarification' })

        expect(request).toHaveBeenCalledWith({
            method: 'POST',
            path: '/api/projects/17/tasks/message-parent/',
            body: { message: 'Need clarification' },
        })
    })
})
