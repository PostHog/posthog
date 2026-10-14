import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { BindLogic } from 'kea'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { EXIT_NODE_ID, NEW_WORKFLOW, TRIGGER_NODE_ID, workflowLogic } from '../../workflowLogic'
import { hogFlowEditorLogic } from '../hogFlowEditorLogic'
import { DESTINATION_TEMPLATES } from '../stepPicker/stepCatalogTestTemplates'
import type { HogFlowAction, HogFlowEdge } from '../types'
import { HogFlowTreeDropzone } from './HogFlowTreeDropzone'

const LOGIC_PROPS = { id: 'new' }
const BRANCH_ID = 'route-by-plan'

const edge = (from: string, to: string, type: 'continue' | 'branch', index?: number): HogFlowEdge => ({
    from,
    to,
    type,
    index,
})

const conditionalBranch: HogFlowAction = {
    id: BRANCH_ID,
    type: 'conditional_branch',
    name: 'Route by plan',
    description: '',
    created_at: 0,
    updated_at: 0,
    config: { conditions: [{ name: 'Paid', filters: {} }] },
}

const LINEAR = {
    actions: NEW_WORKFLOW.actions,
    edges: [edge(TRIGGER_NODE_ID, EXIT_NODE_ID, 'continue')],
    insertionEdge: edge(TRIGGER_NODE_ID, EXIT_NODE_ID, 'continue'),
    isBranchJoin: false,
    joinEdges: undefined,
    expectedEdges: (added: string) => [edge(TRIGGER_NODE_ID, added, 'continue'), edge(added, EXIT_NODE_ID, 'continue')],
}

const BRANCH_JOIN = {
    actions: [NEW_WORKFLOW.actions[0], conditionalBranch, NEW_WORKFLOW.actions[1]],
    edges: [
        edge(TRIGGER_NODE_ID, BRANCH_ID, 'continue'),
        edge(BRANCH_ID, EXIT_NODE_ID, 'branch', 0),
        edge(BRANCH_ID, EXIT_NODE_ID, 'continue'),
    ],
    insertionEdge: edge(BRANCH_ID, EXIT_NODE_ID, 'branch', 0),
    isBranchJoin: true,
    joinEdges: [edge(BRANCH_ID, EXIT_NODE_ID, 'branch', 0), edge(BRANCH_ID, EXIT_NODE_ID, 'continue')],
    expectedEdges: (added: string) => [
        edge(TRIGGER_NODE_ID, BRANCH_ID, 'continue'),
        edge(BRANCH_ID, added, 'branch', 0),
        edge(BRANCH_ID, added, 'continue'),
        edge(added, EXIT_NODE_ID, 'continue'),
    ],
}

describe('HogFlowTreeDropzone', () => {
    const enableFlags = (flags: string[]): void => {
        featureFlagLogic.actions.setFeatureFlags(flags, Object.fromEntries(flags.map((flag) => [flag, true])))
    }

    const renderDropzone = (insertion: typeof LINEAR | typeof BRANCH_JOIN): void => {
        workflowLogic(LOGIC_PROPS).actions.setWorkflowInfo({ actions: insertion.actions, edges: insertion.edges })
        render(
            <BindLogic logic={workflowLogic} props={LOGIC_PROPS}>
                <BindLogic logic={hogFlowEditorLogic} props={LOGIC_PROPS}>
                    <HogFlowTreeDropzone
                        active={false}
                        draggedActionId={null}
                        draggedActionIdRef={{ current: null }}
                        onDragEnd={() => {}}
                        edge={insertion.insertionEdge}
                        isBranchJoin={insertion.isBranchJoin}
                        joinEdges={insertion.joinEdges}
                    />
                </BindLogic>
            </BindLogic>
        )
    }

    const openInsertionPoint = (): void => {
        fireEvent.click(document.querySelector('[data-attr="workflow-tree-insert-action"]') as HTMLElement)
    }

    beforeEach(() => {
        useMocks({
            get: {
                '/api/projects/:team_id/hog_function_templates': {
                    count: DESTINATION_TEMPLATES.length,
                    results: DESTINATION_TEMPLATES,
                },
            },
        })
        initKeaTests()
        featureFlagLogic.mount()
        hogFlowEditorLogic(LOGIC_PROPS).mount()
    })

    afterEach(() => {
        cleanup()
    })

    it.each([
        ['an edge', LINEAR],
        ['a branch join', BRANCH_JOIN],
    ])('inserts the step picked in the step picker at %s', async (_, insertion) => {
        enableFlags([FEATURE_FLAGS.WORKFLOWS_STEP_PICKER, FEATURE_FLAGS.WORKFLOW_AI_TASK_ACTION])
        renderDropzone(insertion)

        openInsertionPoint()
        fireEvent.change(screen.getByPlaceholderText('Search steps'), { target: { value: 'Create AI task' } })
        const row = (
            await screen.findByText('Create AI task', { selector: '[data-attr="workflow-step-picker-step-title"]' })
        ).closest('li')
        fireEvent.click(within(row as HTMLElement).getByLabelText('Add step'))

        const workflow = workflowLogic(LOGIC_PROPS).values.workflow
        const added = workflow.actions.find((action) => action.name === 'Create AI task')
        expect(added).toMatchObject({
            type: 'function',
            config: {
                template_id: 'template-posthog-create-task',
                inputs: expect.objectContaining({ non_failure_status_codes: { value: [409] } }),
            },
            output_variable: { key: 'task', result_path: null, label: 'Task' },
        })
        expect(workflow.edges).toEqual(expect.arrayContaining(insertion.expectedEdges(added!.id)))
        expect(workflow.edges).toHaveLength(insertion.expectedEdges(added!.id).length)
        await waitFor(() => expect(screen.queryByPlaceholderText('Search steps')).not.toBeInTheDocument())
    })

    it('opens the existing picker popover when the step picker flag is off', async () => {
        enableFlags([FEATURE_FLAGS.WORKFLOW_AI_TASK_ACTION])
        renderDropzone(LINEAR)

        openInsertionPoint()

        expect(await screen.findByText('Audience split')).toBeInTheDocument()
        expect(screen.queryByPlaceholderText('Search steps')).not.toBeInTheDocument()
    })
})
