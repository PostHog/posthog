import '@testing-library/jest-dom'

import { act, cleanup, fireEvent, render } from '@testing-library/react'
import { BindLogic, Provider } from 'kea'
import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { performWideEventsQueryInTwoPhases } from 'scenes/hog-functions/sampleEventsQuery'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { AccessControlLevel } from '~/types'

import { hogFlowEditorLogic } from './hogflows/hogFlowEditorLogic'
import { hogFlowEditorTestLogic } from './hogflows/panel/testing/hogFlowEditorTestLogic'
import { HogFlow } from './hogflows/types'
import { workflowLogic } from './workflowLogic'
import { WorkflowSceneHeader } from './WorkflowSceneHeader'

jest.mock('scenes/hog-functions/sampleEventsQuery', () => ({
    ...jest.requireActual('scenes/hog-functions/sampleEventsQuery'),
    performWideEventsQueryInTwoPhases: jest.fn(),
}))

const WORKFLOW_ID = 'wf-header-1'

const ACTIVE_WITH_DRAFT: HogFlow = {
    id: WORKFLOW_ID,
    name: 'Header test',
    actions: [
        {
            id: 'signup_trigger',
            type: 'trigger',
            name: 'Trigger',
            description: '',
            created_at: 0,
            updated_at: 0,
            config: { type: 'event', filters: {} },
        },
        {
            id: 'exit_node',
            type: 'exit',
            name: 'Exit',
            description: '',
            created_at: 0,
            updated_at: 0,
            config: { reason: 'Default exit' },
        },
    ],
    edges: [{ from: 'signup_trigger', to: 'exit_node', type: 'continue' }],
    conversion: { filters: [] },
    exit_condition: 'exit_only_at_end',
    version: 1,
    status: 'active',
    user_access_level: AccessControlLevel.Editor,
    team_id: 1,
    trigger: { type: 'event', filters: {} } as HogFlow['trigger'],
    created_at: '2026-05-01T00:00:00.000Z',
    updated_at: '2026-05-01T00:00:00.000Z',
    draft: { name: 'Header test', actions: [], edges: [] },
    draft_updated_at: '2026-05-01T00:01:00.000Z',
}

// The label and order of the buttons a person points at, as rendered.
const toolbar = (): string[] =>
    Array.from(document.querySelectorAll('[data-attr="workflow-publish"],[data-attr="workflow-save"]')).map(
        (el) => `${el.getAttribute('data-attr')}:${el.textContent ?? ''}`
    )

describe('WorkflowSceneHeader', () => {
    let logic: ReturnType<typeof workflowLogic.build>

    let workflowOnServer: HogFlow = ACTIVE_WITH_DRAFT

    beforeEach(() => {
        useMocks({
            get: {
                '/api/environments/:team_id/hog_flows/:id/': () => [200, workflowOnServer],
                '/api/environments/:team_id/hog_flows/:id/schedules': { results: [] },
                '/api/projects/:team_id/hog_function_templates/': { results: [], count: 0 },
            },
        })
        initKeaTests()
        featureFlagLogic.actions.setFeatureFlags(['workflows-testing-v2'], { 'workflows-testing-v2': true })
    })

    it('hides the new header test action when enhanced testing is off', async () => {
        featureFlagLogic.actions.setFeatureFlags([], {})
        await loadHeader(ACTIVE_WITH_DRAFT)
        renderHeader()

        expect(document.querySelector('[data-attr="workflow-test"]')).not.toBeInTheDocument()
    })

    const loadHeader = async (workflow: HogFlow): Promise<void> => {
        workflowOnServer = workflow
        logic = workflowLogic({ id: WORKFLOW_ID })
        logic.mount()
        await act(async () => {
            await logic.asyncActions.loadWorkflow()
        })
    }

    const renderHeader = (): void => {
        render(
            <Provider>
                <BindLogic logic={workflowLogic} props={{ id: WORKFLOW_ID }}>
                    <WorkflowSceneHeader id={WORKFLOW_ID} />
                </BindLogic>
            </Provider>
        )
    }

    const testButton = (): HTMLElement => document.querySelector('[data-attr="workflow-test"]') as HTMLElement

    afterEach(() => {
        cleanup()
        logic?.unmount()
    })

    it('keeps the same buttons in the same order when edits make the form dirty', async () => {
        await loadHeader(ACTIVE_WITH_DRAFT)
        renderHeader()

        // Auto-save has just landed: a draft is staged and the form is clean.
        const clean = toolbar()
        expect(clean).toEqual(['workflow-save:Save draft', 'workflow-publish:Publish'])

        act(() => {
            logic.actions.setWorkflowValue('name', 'Still typing')
        })

        // The pointer has not moved, so neither has the button under it.
        expect(toolbar()).toEqual(clean)
    })

    it.each([
        ['primary', 'a saved draft', 'draft', false],
        ['secondary', 'a draft with unsaved edits', 'draft', true],
        ['secondary', 'an enabled workflow', 'active', false],
        ['secondary', 'an archived workflow', 'archived', false],
    ] as const)('shows Test as the %s action for %s', async (role, _, status, edited) => {
        await loadHeader({ ...ACTIVE_WITH_DRAFT, status, draft: undefined, draft_updated_at: undefined })
        renderHeader()
        if (edited) {
            act(() => logic.actions.setWorkflowValue('name', 'Still typing'))
        }

        expect(testButton()).toHaveClass(`LemonButton--${role}`)
    })

    it('keeps Test out of the way of a viewer, who cannot run tests', async () => {
        await loadHeader({ ...ACTIVE_WITH_DRAFT, status: 'draft', user_access_level: AccessControlLevel.Viewer })
        renderHeader()

        expect(testButton()).toHaveClass('LemonButton--secondary')
        expect(testButton()).toHaveAttribute('aria-disabled', 'true')
    })

    it.each([
        ['from another tab', 'invocations', false],
        ['with the test pane already loaded', 'workflow', true],
    ])('opens the test pane %s and runs the trigger straight away', async (_, startTab, paneAlreadyLoaded) => {
        ;(performWideEventsQueryInTwoPhases as jest.Mock).mockResolvedValue({ results: [] })
        const testedSteps: string[] = []
        useMocks({
            post: {
                '/api/environments/:team_id/hog_flows/:id/invocations': async ({ request }) => {
                    const body = (await request.json()) as { current_action_id: string; testing_v2: boolean }
                    expect(body.testing_v2).toBe(true)
                    testedSteps.push(body.current_action_id)
                    return [200, { status: 'success', nextActionId: 'exit_node', logs: [] }]
                },
            },
        })
        await loadHeader({ ...ACTIVE_WITH_DRAFT, draft: undefined, draft_updated_at: undefined })
        router.actions.push(`/workflows/${WORKFLOW_ID}/${startTab}`)
        renderHeader()
        const editor = hogFlowEditorLogic({ id: WORKFLOW_ID })
        const testPane = hogFlowEditorTestLogic({ id: WORKFLOW_ID })
        if (paneAlreadyLoaded) {
            editor.mount()
            testPane.mount()
            await expectLogic(testPane).toDispatchActions(['loadSampleGlobalsSuccess'])
        }

        fireEvent.click(testButton())
        if (!paneAlreadyLoaded) {
            editor.mount()
            testPane.mount()
        }

        expect(router.values.location.pathname).toMatch(new RegExp(`/workflows/${WORKFLOW_ID}/workflow$`))
        expect(editor.values).toMatchObject({ mode: 'test', selectedNodeId: 'signup_trigger' })
        await expectLogic(testPane).toDispatchActions(['submitTestInvocationSuccess'])
        expect(testedSteps).toEqual(['signup_trigger'])
        expect(testPane.values).toMatchObject({
            testResult: { status: 'success', nextActionId: 'exit_node' },
            eventPanelOpen: [],
        })
        testPane.unmount()
        editor.unmount()
    })

    it('drops the run when the test event fails to load, so a later reload does not start it', async () => {
        ;(performWideEventsQueryInTwoPhases as jest.Mock).mockRejectedValueOnce(new Error('query failed'))
        const testedSteps: string[] = []
        useMocks({
            post: {
                '/api/environments/:team_id/hog_flows/:id/invocations': async ({ request }) => {
                    testedSteps.push(((await request.json()) as { current_action_id: string }).current_action_id)
                    return [200, { status: 'success', nextActionId: 'exit_node', logs: [] }]
                },
            },
        })
        await loadHeader({ ...ACTIVE_WITH_DRAFT, draft: undefined, draft_updated_at: undefined })
        renderHeader()

        fireEvent.click(testButton())
        const editor = hogFlowEditorLogic({ id: WORKFLOW_ID })
        editor.mount()
        const testPane = hogFlowEditorTestLogic({ id: WORKFLOW_ID })
        testPane.mount()
        await expectLogic(testPane).toDispatchActions(['loadSampleGlobalsSuccess'])
        ;(performWideEventsQueryInTwoPhases as jest.Mock).mockResolvedValue({ results: [] })
        await expectLogic(testPane, () => testPane.actions.loadSampleGlobals()).toDispatchActions([
            'loadSampleGlobalsSuccess',
        ])
        await expectLogic(testPane).toFinishAllListeners()

        expect(testedSteps).toEqual([])
        testPane.unmount()
        editor.unmount()
    })
})
