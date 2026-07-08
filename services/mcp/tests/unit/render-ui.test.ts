import { describe, expect, it } from 'vitest'
import { z } from 'zod'

import { isToolCallPayload, type ToolResultPayload } from '@/lib/build-tool-result'
import { RENDER_UI_RESOURCE_URI, URI_MAP } from '@/resources/ui-apps.generated'
import { createRenderUiTool, getRenderableToolNames, RENDER_UI_TOOL_NAME } from '@/tools/render-ui'
import { type Context, type Tool, type ZodObjectAny } from '@/tools/types'

const mockContext = {
    getDistinctId: async () => 'test-distinct-id',
} as unknown as Context

function makeTool(name: string, resourceUri?: string): Tool<ZodObjectAny> {
    return {
        name,
        title: name,
        description: `Tool ${name}`,
        schema: z.object({}),
        scopes: [],
        annotations: { destructiveHint: false, idempotentHint: true, openWorldHint: false, readOnlyHint: true },
        handler: async () => ({ ok: true }),
        ...(resourceUri ? { _meta: { ui: { resourceUri } } } : {}),
    }
}

// A detail app (`survey`) is dispatchable; a custom app (`debug`) is not.
const surveyTool = makeTool('survey-get', URI_MAP['survey'])
const debugTool = makeTool('debug-tool', URI_MAP['debug'])
const plainTool = makeTool('plain-tool')

describe('render-ui tool', () => {
    it('only counts tools whose UI app has a generated view as renderable', () => {
        expect(getRenderableToolNames([surveyTool, debugTool, plainTool])).toEqual(['survey-get'])
    })

    it('excludes non-read-only tools so render-ui cannot dispatch mutating tools', () => {
        const mutatingTool = makeTool('survey-launch', URI_MAP['survey'])
        mutatingTool.annotations.readOnlyHint = false
        expect(getRenderableToolNames([mutatingTool])).toEqual([])
    })

    it('returns null when no tool has a renderable UI app', () => {
        expect(createRenderUiTool([debugTool, plainTool], mockContext)).toBeNull()
    })

    it('restricts tool_name to the renderable tools', () => {
        const tool = createRenderUiTool([surveyTool, debugTool, plainTool], mockContext)
        expect(tool).not.toBeNull()
        const schema = tool!.schema

        expect(schema.safeParse({ tool_name: 'survey-get', tool_input: { surveyId: 'abc' } }).success).toBe(true)
        // Non-UI and custom-app tools are not valid enum members.
        expect(schema.safeParse({ tool_name: 'plain-tool' }).success).toBe(false)
        expect(schema.safeParse({ tool_name: 'debug-tool' }).success).toBe(false)
    })

    it('emits a render directive payload with the envelope and render-ui resourceUri', async () => {
        const tool = createRenderUiTool([surveyTool, debugTool, plainTool], mockContext)!
        const result = (await tool.handler(mockContext, {
            tool_name: 'survey-get',
            tool_input: { surveyId: 'abc' },
        })) as ToolResultPayload

        expect(isToolCallPayload(result)).toBe(true)
        expect(result.structuredContent).toEqual({
            tool_name: 'survey-get',
            tool_input: { surveyId: 'abc' },
            app_key: 'survey',
            _analytics: { distinctId: 'test-distinct-id', toolName: RENDER_UI_TOOL_NAME },
        })
        expect(result._meta?.ui).toEqual({ resourceUri: RENDER_UI_RESOURCE_URI })
    })

    it('defaults tool_input to an empty object when omitted', async () => {
        const tool = createRenderUiTool([surveyTool], mockContext)!
        const result = (await tool.handler(mockContext, { tool_name: 'survey-get' })) as ToolResultPayload
        expect((result.structuredContent as Record<string, unknown>).tool_input).toEqual({})
    })

    it('does not execute the inner tool — it only emits a render directive', async () => {
        let innerCalled = false
        const spyTool = makeTool('survey-get', URI_MAP['survey'])
        spyTool.handler = async () => {
            innerCalled = true
            return { ok: true }
        }
        const tool = createRenderUiTool([spyTool], mockContext)!
        await tool.handler(mockContext, { tool_name: 'survey-get' })
        expect(innerCalled).toBe(false)
    })
})
