import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { removeProjectIdIfPresent } from 'lib/utils/kea-router'
import { MAX_SIDE_PANEL_ID } from 'scenes/max/components/PhaiSidePanelChat'
import { maxMocks } from 'scenes/max/testUtils'

import { sidePanelStateLogic } from '~/layout/navigation-3000/sidepanel/sidePanelStateLogic'
import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { SidePanelTab } from '~/types'

import { runnerPanelLogic, toolStreamEventsLogic } from 'products/posthog_ai/frontend/api/logics'
import type { ToolStreamEvent } from 'products/posthog_ai/frontend/api/types'

import { extractCreatedWorkflowId, newWorkflowAgentLogic } from './newWorkflowAgentLogic'

const WORKFLOW_ID = '2f1e9c3a-5b7d-4e8f-9a0b-1c2d3e4f5a6b'

function createEvent(overrides: Partial<ToolStreamEvent>): ToolStreamEvent {
    return {
        streamKey: 'draft-1',
        toolCallId: 'call-1',
        toolName: 'workflows-create',
        rawToolName: 'exec',
        phase: 'completed',
        source: 'live',
        invocation: {
            toolCallId: 'call-1',
            rawServerName: 'posthog',
            rawToolName: 'exec',
            input: {},
            output: { id: WORKFLOW_ID },
            status: 'completed',
            contentBlocks: [],
        },
        ...overrides,
    }
}

describe('newWorkflowAgentLogic', () => {
    let logic: ReturnType<typeof newWorkflowAgentLogic.build>

    beforeEach(() => {
        useMocks(maxMocks)
        initKeaTests()
        sidePanelStateLogic.mount()
        sidePanelStateLogic.actions.setSidePanelAvailable(true)
        router.actions.push('/workflows/new/workflow', {}, {})
        logic = newWorkflowAgentLogic()
        logic.mount()
        runnerPanelLogic({ panelId: MAX_SIDE_PANEL_ID }).actions.setActiveCreation({ streamKey: 'draft-1' })
    })

    afterEach(() => {
        logic?.unmount()
    })

    // The exec wrapper's output shape is not pinned by a type, so each envelope the agent runtime has
    // produced must still yield the id, and anything without one must not route the user anywhere.
    it.each([
        { name: 'a bare object', output: { id: WORKFLOW_ID }, expected: WORKFLOW_ID },
        { name: 'structuredContent', output: { structuredContent: { id: WORKFLOW_ID } }, expected: WORKFLOW_ID },
        {
            name: 'a JSON text block',
            output: { content: [{ type: 'text', text: `{"id":"${WORKFLOW_ID}"}` }] },
            expected: WORKFLOW_ID,
        },
        { name: 'a JSON string', output: `{"id":"${WORKFLOW_ID}","name":"x"}`, expected: WORKFLOW_ID },
        { name: 'an error envelope', output: { isError: true, id: WORKFLOW_ID }, expected: null },
        { name: 'a non-uuid id', output: { id: 'new' }, expected: null },
        { name: 'nothing', output: undefined, expected: null },
    ])('extractCreatedWorkflowId reads $name', ({ output, expected }) => {
        expect(extractCreatedWorkflowId(output)).toBe(expected)
    })

    it('opens the side panel and routes to the draft once this run creates a workflow', async () => {
        await expectLogic(logic, () => {
            toolStreamEventsLogic.actions.emitToolEvent(createEvent({}))
        }).toFinishAllListeners()

        expect(sidePanelStateLogic.values.selectedTab).toBe(SidePanelTab.Max)
        expect(sidePanelStateLogic.values.sidePanelOpen).toBe(true)
        expect(removeProjectIdIfPresent(router.values.location.pathname)).toBe(`/workflows/${WORKFLOW_ID}/workflow`)
    })

    // The bus is global: a replay on reload, another run's create, or a still-streaming call must not
    // yank the user off the composer.
    it.each([
        { name: 'a replayed event', overrides: { source: 'replay' as const } },
        { name: 'another stream', overrides: { streamKey: 'other-run' } },
        { name: 'an unfinished call', overrides: { phase: 'started' as const } },
        { name: 'a different tool', overrides: { toolName: 'workflows-get' } },
    ])('ignores $name', async ({ overrides }) => {
        await expectLogic(logic, () => {
            toolStreamEventsLogic.actions.emitToolEvent(createEvent(overrides))
        }).toFinishAllListeners()

        expect(sidePanelStateLogic.values.sidePanelOpen).toBe(false)
        expect(removeProjectIdIfPresent(router.values.location.pathname)).toBe('/workflows/new/workflow')
    })
})
