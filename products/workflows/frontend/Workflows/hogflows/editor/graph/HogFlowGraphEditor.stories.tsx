import type { Meta, StoryFn } from '@storybook/react'
import { BindLogic, useValues } from 'kea'

import { SpinnerOverlay } from '@posthog/lemon-ui'

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

const WorkflowStory = ({ id }: { id: string }): JSX.Element => (
    <BindLogic logic={workflowLogic} props={{ id }}>
        <div className="h-screen [&>div]:!h-full [&>div]:!max-h-none">
            <StorybookWorkflow />
        </div>
    </BindLogic>
)

function StorybookWorkflow(): JSX.Element {
    const { originalWorkflow } = useValues(workflowLogic)

    return (
        <div className="flex h-full flex-col">
            {originalWorkflow ? <HogFlowEditor key={originalWorkflow.id} /> : <SpinnerOverlay />}
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
