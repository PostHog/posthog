import '@testing-library/jest-dom'

import { act, cleanup, render } from '@testing-library/react'
import { BindLogic, Provider } from 'kea'

import { sceneLayoutLogic } from '~/layout/scenes/sceneLayoutLogic'
import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { HogFlow } from './hogflows/types'
import { workflowLogic } from './workflowLogic'
import { WorkflowSceneHeader } from './WorkflowSceneHeader'

const WORKFLOW_ID = 'wf-header-1'

const ACTIVE_WITH_DRAFT: HogFlow = {
    id: WORKFLOW_ID,
    name: 'Header test',
    actions: [
        {
            id: 'trigger_node',
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
    edges: [{ from: 'trigger_node', to: 'exit_node', type: 'continue' }],
    conversion: { window_minutes: null, filters: [] },
    exit_condition: 'exit_only_at_end',
    version: 1,
    status: 'active',
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

const copyCodeButtons = (): Element[] => Array.from(document.querySelectorAll('[data-attr="workflow-copy-code"]'))
const copyCodeMenuItems = (): Element[] => Array.from(document.querySelectorAll('[data-attr="workflow-copy-code-btn"]'))

describe('WorkflowSceneHeader', () => {
    let logic: ReturnType<typeof workflowLogic.build>

    beforeEach(async () => {
        useMocks({
            get: {
                '/api/environments/:team_id/hog_flows/:id/': ACTIVE_WITH_DRAFT,
                '/api/environments/:team_id/hog_flows/:id/schedules': { results: [] },
                '/api/projects/:team_id/hog_function_templates/': { results: [], count: 0 },
            },
        })
        initKeaTests()
        const scenePanel = document.createElement('div')
        document.body.appendChild(scenePanel)
        sceneLayoutLogic.mount()
        sceneLayoutLogic.actions.registerScenePanelElement(scenePanel)
        logic = workflowLogic({ id: WORKFLOW_ID })
        logic.mount()
        await act(async () => {
            await logic.asyncActions.loadWorkflow()
        })
    })

    afterEach(() => {
        cleanup()
        logic?.unmount()
        document.body.innerHTML = ''
    })

    it('keeps the same buttons in the same order when edits make the form dirty', () => {
        render(
            <Provider>
                <BindLogic logic={workflowLogic} props={{ id: WORKFLOW_ID }}>
                    <WorkflowSceneHeader id={WORKFLOW_ID} />
                </BindLogic>
            </Provider>
        )

        // Auto-save has just landed: a draft is staged and the form is clean.
        const clean = toolbar()
        expect(clean).toEqual(['workflow-save:Save draft', 'workflow-publish:Publish'])

        act(() => {
            logic.actions.setWorkflowValue('name', 'Still typing')
        })

        // The pointer has not moved, so neither has the button under it.
        expect(toolbar()).toEqual(clean)
    })

    it('offers copy code only from the "..." menu for a workflow the app owns', () => {
        render(
            <Provider>
                <BindLogic logic={workflowLogic} props={{ id: WORKFLOW_ID }}>
                    <WorkflowSceneHeader id={WORKFLOW_ID} />
                </BindLogic>
            </Provider>
        )

        expect(copyCodeButtons()).toHaveLength(0)
        expect(copyCodeMenuItems()).toHaveLength(1)
        expect(copyCodeMenuItems()[0]).toHaveTextContent('Copy code')
    })

    it('puts copy code where save sits for a code-managed workflow, even with edits in the form', async () => {
        logic.unmount()
        useMocks({
            get: {
                '/api/environments/:team_id/hog_flows/:id/': {
                    ...ACTIVE_WITH_DRAFT,
                    managed_by: 'code',
                    source_repository: 'github.com/example/flows',
                    source_path: 'workflows/welcome.ts',
                },
            },
        })
        logic = workflowLogic({ id: WORKFLOW_ID })
        logic.mount()
        await act(async () => {
            await logic.asyncActions.loadWorkflow()
        })
        render(
            <Provider>
                <BindLogic logic={workflowLogic} props={{ id: WORKFLOW_ID }}>
                    <WorkflowSceneHeader id={WORKFLOW_ID} />
                </BindLogic>
            </Provider>
        )

        act(() => {
            logic.actions.setWorkflowValue('name', 'Edited in the UI')
        })

        expect(toolbar()).toEqual([])
        expect(copyCodeButtons()).toHaveLength(1)
        expect(copyCodeButtons()[0]).toHaveClass('LemonButton--primary')
        expect(copyCodeMenuItems()).toHaveLength(0)
        expect(document.querySelector('[data-attr="workflow-code-managed-help"]')).not.toBeNull()
        expect(document.querySelector('[data-attr="workflow-managed-by-code"]')).not.toBeNull()
    })
})
