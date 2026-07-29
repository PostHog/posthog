import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'

import type { ToolStreamEvent } from '../types/streamTypes'
import { foregroundStreamLogic } from './foregroundStreamLogic'
import { toolNavigationLogic } from './toolNavigationLogic'
import { toolStreamEventsLogic } from './toolStreamEventsLogic'

const STREAM_KEY = 'run-1'

function creationEvent(
    toolName: string,
    output: Record<string, unknown>,
    overrides: Partial<ToolStreamEvent> = {}
): ToolStreamEvent {
    return {
        streamKey: STREAM_KEY,
        toolCallId: `tc-${toolName}`,
        toolName,
        rawToolName: 'exec',
        phase: 'completed',
        invocation: {
            toolCallId: `tc-${toolName}`,
            rawServerName: 'posthog',
            rawToolName: 'exec',
            input: {},
            output,
            status: 'completed',
        } as unknown as ToolStreamEvent['invocation'],
        source: 'live',
        ...overrides,
    }
}

describe('toolNavigationLogic', () => {
    let logic: ReturnType<typeof toolNavigationLogic.build>

    beforeEach(() => {
        initKeaTests()
        logic = toolNavigationLogic()
        logic.mount()
        foregroundStreamLogic.actions.setForegroundStream(STREAM_KEY, 'test-surface')
        router.actions.push('/workflows/library')
    })

    afterEach(() => {
        logic?.unmount()
    })

    it('routes to a created workflow immediately', async () => {
        toolStreamEventsLogic.actions.emitToolEvent(creationEvent('workflows-create', { id: 'wf-1' }))
        await expectLogic(logic).toFinishAllListeners()

        expect(router.values.location.pathname.endsWith('/workflows/wf-1/workflow')).toBe(true)
    })

    it.each([
        ['not in the foreground', { streamKey: 'background-run' }],
        ['replayed from history', { source: 'replay' as const }],
    ])('ignores a workflow creation %s', async (_label, overrides) => {
        toolStreamEventsLogic.actions.emitToolEvent(creationEvent('workflows-create', { id: 'wf-1' }, overrides))
        await expectLogic(logic).toFinishAllListeners()

        expect(router.values.location.pathname.endsWith('/workflows/library')).toBe(true)
    })

    it.each([
        ['template only routes to the template at turn end', false, '/workflows/library/templates/tpl-1'],
        ['template plus workflow routes to the workflow only', true, '/workflows/wf-1/workflow'],
    ])('creation auto-route: %s', async (_label, alsoCreatesWorkflow, expectedPathTail) => {
        toolStreamEventsLogic.actions.emitToolEvent(creationEvent('workflows-create-email-template', { id: 'tpl-1' }))
        await expectLogic(logic).toFinishAllListeners()
        // No mid-turn routing for templates: a workflow later in the turn must win.
        expect(router.values.location.pathname.endsWith('/workflows/library')).toBe(true)

        if (alsoCreatesWorkflow) {
            toolStreamEventsLogic.actions.emitToolEvent(creationEvent('workflows-create', { id: 'wf-1' }))
        }
        toolStreamEventsLogic.actions.emitTurnCompleteEvent({ streamKey: STREAM_KEY })
        await expectLogic(logic).toFinishAllListeners()

        expect(router.values.location.pathname.endsWith(expectedPathTail)).toBe(true)
    })

    it.each([
        ['navigates to a same-origin url', () => `${window.location.origin}/insights/abc123`, '/insights/abc123'],
        ['ignores a foreign-origin url', () => 'https://evil.example.com/insights/abc123', '/workflows/library'],
    ])('navigate-user completion: %s', async (_label, buildUrl, expectedPathTail) => {
        toolStreamEventsLogic.actions.emitToolEvent(creationEvent('navigate-user', { url: buildUrl() }))
        await expectLogic(logic).toFinishAllListeners()

        expect(router.values.location.pathname.endsWith(expectedPathTail)).toBe(true)
    })
})
