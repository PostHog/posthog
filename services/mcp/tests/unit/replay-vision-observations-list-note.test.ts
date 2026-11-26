import { describe, expect, it, vi } from 'vitest'

import { createExecTool } from '@/tools/exec'
import { GENERATED_TOOLS } from '@/tools/generated/replay_vision'
import { getToolDefinition } from '@/tools/toolDefinitions'
import type { Context, Tool, ZodObjectAny } from '@/tools/types'

const TOOL_NAME = 'vision-observations-list'

function context(): Context {
    return {
        api: {
            request: vi.fn().mockResolvedValue({ count: 0, next: null, previous: null, results: [] }),
            getProjectBaseUrl: (projectId: string) => `https://us.posthog.com/project/${projectId}`,
        } as any,
        stateManager: { getProjectId: vi.fn().mockResolvedValue('42') } as any,
        env: {} as any,
        sessionManager: {} as any,
        cache: {} as any,
        getDistinctId: async () => 'test-distinct-id',
        trackEvent: async () => {},
    }
}

describe('vision-observations-list with no observations', () => {
    it('tells the agent how to create a summary with an inline scan', async () => {
        const definition = getToolDefinition(TOOL_NAME)
        const tool = {
            ...GENERATED_TOOLS[TOOL_NAME]!(),
            title: definition.title,
            description: definition.description,
            scopes: [],
            annotations: definition.annotations,
        } as Tool<ZodObjectAny>
        const ctx = context()
        const exec = createExecTool([tool], ctx, '', '', undefined)

        const output = await exec.handler(ctx, { command: `call ${TOOL_NAME} {"session_id": "session-1"}` })

        expect(String(output)).toContain('`vision-scanners-inline-scan`')
        expect(String(output)).toContain('`built_in: "summarize_recording"`')
    })
})
