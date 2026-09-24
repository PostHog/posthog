import type { Meta, StoryFn } from '@storybook/react'
import { BindLogic, useValues } from 'kea'

import { SpinnerOverlay } from '@posthog/lemon-ui'

import { FEATURE_FLAGS } from 'lib/constants'
import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { expect, userEvent, waitFor, within } from 'storybook/test'

import { workflowLogic } from '../../../workflowLogic'
import { HogFlowEditor } from '../../HogFlowEditor'
import {
    CUSTOMER_ONBOARDING_AND_RETENTION_WORKFLOW_ID,
    workflowEditorStoryDecorator,
} from '../workflowEditorStoryFixtures'

const meta: Meta<typeof HogFlowEditor> = {
    title: 'Products/Workflows/Editor/Graph',
    component: HogFlowEditor,
    parameters: {
        layout: 'fullscreen',
        testOptions: {
            waitForLoadersToDisappear: true,
            waitForSelector: '[data-attr=workflow-editor]',
            viewport: { width: 1600, height: 1000 },
        },
    },
    decorators: [workflowEditorStoryDecorator],
}
export default meta

const WorkflowStory = ({ id, className = '' }: { id: string; className?: string }): JSX.Element => (
    <BindLogic logic={workflowLogic} props={{ id }}>
        <div className={`h-screen [&>div]:!h-full [&>div]:!max-h-none ${className}`}>
            <StorybookWorkflow />
        </div>
    </BindLogic>
)

function StorybookWorkflow(): JSX.Element {
    const { originalWorkflow } = useValues(workflowLogic)

    return (
        <div className="flex h-full flex-col">
            {originalWorkflow ? <HogFlowEditor key={originalWorkflow.id} isTreeView={false} /> : <SpinnerOverlay />}
        </div>
    )
}

export const NewWorkflow: StoryFn = () => <WorkflowStory id="new" />
export const CustomerOnboardingAndRetention: StoryFn = () => (
    <WorkflowStory id={CUSTOMER_ONBOARDING_AND_RETENTION_WORKFLOW_ID} />
)
export const SupportSlaRouting: StoryFn = () => <WorkflowStory id="example-support-sla-routing" />
export const RenewalWindowAlerts: StoryFn = () => <WorkflowStory id="example-renewal-window-alerts" />
export const PendingTicketCleanup: StoryFn = () => <WorkflowStory id="example-pending-ticket-cleanup" />
export const AddOnPromotionEmails: StoryFn = () => <WorkflowStory id="example-add-on-promotion-emails" />

// 32rem sits below the 48rem container-query breakpoint the editor uses to stack the settings
// panel under the graph, so this story exercises the narrow layout.
export const NarrowWorkflow: StoryFn = () => (
    <WorkflowStory id={CUSTOMER_ONBOARDING_AND_RETENTION_WORKFLOW_ID} className="w-[32rem] max-w-full" />
)
NarrowWorkflow.parameters = { testOptions: { waitForSelector: '.react-flow__node' } }
export const WithNavigation: StoryFn = () => <App />
WithNavigation.parameters = {
    pageUrl: `${urls.workflow(CUSTOMER_ONBOARDING_AND_RETENTION_WORKFLOW_ID, 'workflow')}?view=graph`,
    featureFlags: [FEATURE_FLAGS.WORKFLOWS_LINEAR_VIEW],
    mockDate: '2026-09-04 12:00:00',
    testOptions: {
        waitForSelector: '.react-flow__node',
        viewport: { width: 1280, height: 900 },
        includeNavigationInSnapshot: true,
    },
}

export const BranchDeletionBlocked: StoryFn = WithNavigation.bind({})
BranchDeletionBlocked.parameters = WithNavigation.parameters
BranchDeletionBlocked.play = async ({ canvasElement }) => {
    const branchSelector = '.react-flow__node[data-id="route-by-stage"]'
    await waitFor(() => expect(canvasElement.querySelector(branchSelector)).not.toBeNull())
    const branch = canvasElement.querySelector<HTMLElement>(branchSelector)!
    await userEvent.click(branch)
    await waitFor(() => expect(branch.classList.contains('selected')).toBe(true))

    const logic = workflowLogic({ id: CUSTOMER_ONBOARDING_AND_RETENTION_WORKFLOW_ID })
    const { actions, edges } = logic.values.workflow
    const nodeCount = canvasElement.querySelectorAll('.react-flow__node').length
    const edgeCount = canvasElement.querySelectorAll('.react-flow__edge').length

    await userEvent.keyboard('{Backspace}')
    await within(canvasElement.ownerDocument.body).findByText('Clean up branching steps first')

    expect(canvasElement.querySelectorAll('.react-flow__node')).toHaveLength(nodeCount)
    expect(canvasElement.querySelectorAll('.react-flow__edge')).toHaveLength(edgeCount)
    expect(logic.values.workflow.actions).toEqual(actions)
    expect(logic.values.workflow.edges).toEqual(edges)
}
