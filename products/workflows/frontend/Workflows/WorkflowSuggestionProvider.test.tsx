import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { consumeWorkflowDraftBrief } from 'lib/utils/workflowDraftHandoff'
import { aiSceneView } from 'scenes/max/aiSceneView'
import { maxGlobalLogic } from 'scenes/max/maxGlobalLogic'
import { maxMocks } from 'scenes/max/testUtils'
import { projectLogic } from 'scenes/projectLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { TurnSuggestionCard } from 'products/posthog_ai/frontend/components/TurnSuggestionCard'
import { turnSuggestionsResolveCreate } from 'products/posthog_ai/frontend/generated/api'
import { runStreamLogic } from 'products/posthog_ai/frontend/logics/runStreamLogic'
import { suggestionActionLogic } from 'products/posthog_ai/frontend/logics/suggestionActionLogic'
import { SUGGESTION_FRAMES } from 'products/posthog_ai/frontend/utils/turnSuggestionFixtures'

import { newWorkflowLogic } from './newWorkflowLogic'
import { WorkflowSuggestionProvider } from './WorkflowSuggestionProvider'

jest.mock('products/posthog_ai/frontend/generated/api', () => ({
    ...jest.requireActual('products/posthog_ai/frontend/generated/api'),
    turnSuggestionsResolveCreate: jest.fn(() => Promise.resolve({ recorded: true })),
}))

describe('workflow suggestion destination eligibility', () => {
    beforeEach(() => {
        useMocks(maxMocks)
        initKeaTests()
        newWorkflowLogic.mount()
        sessionStorage.clear()
        jest.mocked(turnSuggestionsResolveCreate).mockClear()
    })

    afterEach(cleanup)

    it.each([
        { view: 'legacy' as const, sandboxEnabled: true, available: false },
        { view: 'new' as const, sandboxEnabled: false, available: false },
        { view: 'new' as const, sandboxEnabled: true, available: true },
    ])('only offers an accessible builder with $view view and sandbox=$sandboxEnabled', async (testCase) => {
        const flags: string[] = [FEATURE_FLAGS.WORKFLOWS_AI_FIRST_NEW, FEATURE_FLAGS.PHAI_SCENE_AUTO_OPEN]
        if (testCase.sandboxEnabled) {
            flags.push(FEATURE_FLAGS.PHAI_SANDBOX_MODE)
        }
        featureFlagLogic.actions.setFeatureFlags(flags, Object.fromEntries(flags.map((flag) => [flag, true])))
        maxGlobalLogic.actions.setPhaiViewMode(testCase.view)
        router.actions.push('/ai', { task: 'task-1' })
        expect(aiSceneView({ taskId: 'task-1', effectivePhaiView: maxGlobalLogic.values.effectivePhaiView })).toBe(
            'runner'
        )

        const stream = runStreamLogic({ streamKey: 'workflow-eligibility' })
        stream.mount()
        for (const [method, params] of [
            ['_posthog/user_message', { content: 'Remind new signups to finish onboarding.' }],
            ['_posthog/turn_suggestion', { ...SUGGESTION_FRAMES.workflow, title: 'Turn this into a workflow' }],
        ] as const) {
            stream.actions.ingestAcpFrame({ type: 'notification', notification: { method, params } })
        }
        stream.actions.setTurnSuggestionLedger({ taskId: 'task-1', muted: false, resolvedTurns: [] })
        const props = { streamKey: 'workflow-eligibility', turnIndex: 0, sessionId: 'task-1', revealDelayMs: 0 }
        render(
            <WorkflowSuggestionProvider>
                <TurnSuggestionCard {...props} />
            </WorkflowSuggestionProvider>
        )

        expect(newWorkflowLogic.values.aiFirstNewEnabled).toBe(testCase.available)
        if (!testCase.available) {
            expect(screen.queryByText('Turn this into a workflow')).not.toBeInTheDocument()
            const action = suggestionActionLogic({ ...props, workflowBuilderAvailable: false })
            action.mount()
            await expectLogic(action, () => action.actions.accept()).toFinishAllListeners()
            expect(router.values.location.pathname).toContain('/ai')
            expect(turnSuggestionsResolveCreate).not.toHaveBeenCalled()
            expect(consumeWorkflowDraftBrief(projectLogic.values.currentProjectId!)).toBeNull()
            action.unmount()
        } else {
            fireEvent.change(screen.getByRole('textbox', { name: 'Workflow brief' }), {
                target: { value: 'Draft a disabled signed_up workflow with a two-day delay.' },
            })
            fireEvent.click(screen.getByRole('button', { name: 'Open workflow builder' }))
            await waitFor(() => expect(router.values.location.pathname).toBe('/project/997/workflows/new/workflow'))
            expect(router.values.searchParams).toEqual({ mode: 'ai' })
            expect(consumeWorkflowDraftBrief(projectLogic.values.currentProjectId!)).toEqual({
                prompt: 'Draft a disabled signed_up workflow with a two-day delay.',
                eventProperties: {
                    source: 'ai_turn_suggestion',
                    task_id: 'task-1',
                    turn_index: 0,
                    team_id: '997',
                },
            })
        }
        stream.unmount()
    })
})
