import type { Meta, StoryObj } from '@storybook/react'
import { BindLogic } from 'kea'

import { mswDecorator } from '~/mocks/browser'

import { Workflow } from '../Workflow'
import { workflowLogic } from '../workflowLogic'
import { HogFlow } from './types'

const WORKFLOW_ID = 'story-workflow'

const now = 1767225600000

/**
 * A conditional branch whose branch edges and continue edge all land on the same step, which is
 * what inserting a branch mid-flow produces. `email` is a second step further down so there is
 * somewhere else to drop a branch edge onto.
 */
const BRANCHING_WORKFLOW: HogFlow = {
    id: WORKFLOW_ID,
    team_id: 1,
    version: 1,
    name: 'Activation sequence',
    status: 'draft',
    exit_condition: 'exit_only_at_end',
    actions: [
        {
            id: 'trigger_node',
            name: 'Trigger',
            description: '',
            type: 'trigger',
            created_at: now,
            updated_at: now,
            config: { type: 'event', filters: {} },
        },
        {
            id: 'cond',
            name: 'Signed up?',
            description: '',
            type: 'conditional_branch',
            created_at: now,
            updated_at: now,
            config: {
                conditions: [
                    { filters: {}, name: 'Activated' },
                    { filters: {}, name: 'Invited a teammate' },
                ],
            },
        },
        {
            id: 'email',
            name: 'Welcome email',
            description: '',
            type: 'delay',
            created_at: now,
            updated_at: now,
            config: { delay_duration: '1h' },
        },
        {
            id: 'exit_node',
            name: 'Exit',
            description: '',
            type: 'exit',
            created_at: now,
            updated_at: now,
            config: { reason: '' },
        },
    ],
    edges: [
        { from: 'trigger_node', to: 'cond', type: 'continue' },
        { from: 'cond', to: 'exit_node', type: 'branch', index: 0 },
        { from: 'cond', to: 'exit_node', type: 'branch', index: 1 },
        { from: 'cond', to: 'email', type: 'continue' },
        { from: 'email', to: 'exit_node', type: 'continue' },
    ],
    created_at: new Date(now).toISOString(),
    updated_at: new Date(now).toISOString(),
} as unknown as HogFlow

const meta: Meta<typeof Workflow> = {
    title: 'Products/Workflows/HogFlowEditor',
    component: Workflow,
    // The canvas autolayouts and animates, so a pixel snapshot would be flaky. The story exists to
    // exercise the editor by hand and in Playwright, not as a visual regression baseline.
    tags: ['test-skip'],
    decorators: [
        mswDecorator({
            get: {
                [`/api/environments/:team_id/hog_flows/${WORKFLOW_ID}/`]: () => [200, BRANCHING_WORKFLOW],
                '/api/environments/:team_id/hog_flows/:id/schedules': () => [200, []],
                '/api/environments/:team_id/hog_function_templates': () => [200, { results: [] }],
                '/api/environments/:team_id/messaging_categories': () => [200, { results: [] }],
            },
            patch: {
                // Echo the submitted workflow back, like the real API — returning the original
                // fixture would make every autosave silently revert the edit under test.
                [`/api/environments/:team_id/hog_flows/${WORKFLOW_ID}/`]: async ({ request }) => [
                    200,
                    { ...BRANCHING_WORKFLOW, ...((await request.json()) as Partial<HogFlow>) },
                ],
            },
        }),
    ],
}
export default meta

type Story = StoryObj<typeof Workflow>

export const BranchingWorkflow: Story = {
    args: { id: WORKFLOW_ID },
    render: (args) => (
        // Mirrors WorkflowScene: the editor resolves workflowLogic from this binding, not from props.
        <BindLogic logic={workflowLogic} props={{ id: WORKFLOW_ID }}>
            <div className="flex h-[600px]">
                <Workflow {...args} />
            </div>
        </BindLogic>
    ),
}
