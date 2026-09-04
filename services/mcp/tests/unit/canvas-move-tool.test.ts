import { describe, expect, it, vi } from 'vitest'
import { z } from 'zod'

import { GENERATED_TOOL_MAP } from '@/tools/generated'
import { getToolDefinition } from '@/tools/toolDefinitions'
import type { Context } from '@/tools/types'

describe('canvas-move tool', () => {
    it('is discoverable with only the required canvas and destination ids', () => {
        const tool = GENERATED_TOOL_MAP['canvas-move']?.()
        expect(tool, 'canvas-move is missing from the generated tool map').not.toBeUndefined()

        const schema = z.toJSONSchema(tool!.schema, { io: 'input', reused: 'inline' }) as {
            properties?: Record<string, unknown>
            required?: string[]
        }

        expect(Object.keys(schema.properties ?? {}).sort()).toEqual(['channel_id', 'id'])
        expect(schema.required?.sort()).toEqual(['channel_id', 'id'])
    })

    it('declares a reversible, idempotent canvas write', () => {
        const definition = getToolDefinition('canvas-move')

        expect(definition.description).toContain('full version history stay intact')
        expect(definition.description).toContain('pin in the current space is cleared')
        expect(definition.required_scopes).toEqual(['canvas:write'])
        expect(definition.annotations?.readOnlyHint).toBe(false)
        expect(definition.annotations?.destructiveHint).toBe(false)
        expect(definition.annotations?.idempotentHint).toBe(true)
    })

    it('patches only the destination space', async () => {
        const request = vi.fn().mockResolvedValue({
            id: 'canvas-1',
            channel: 'space-2',
            pinned: false,
        })
        const context = {
            api: { request },
            stateManager: { getProjectId: vi.fn().mockResolvedValue('17') },
        } as unknown as Context

        const result = await GENERATED_TOOL_MAP['canvas-move']!().handler(context, {
            id: 'canvas-1',
            channel_id: 'space-2',
        })

        expect(request).toHaveBeenCalledWith({
            method: 'PATCH',
            path: '/api/projects/17/canvases/canvas-1/',
            body: { channel_id: 'space-2' },
        })
        expect(result).toMatchObject({ id: 'canvas-1', channel: 'space-2', pinned: false })
    })
})
