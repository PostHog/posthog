import type { Meta, StoryFn } from '@storybook/react'
import { BindLogic, useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { Workflow } from '../../../Workflow'
import { workflowLogic } from '../../../workflowLogic'
import { hogFlowEditorLogic } from '../../hogFlowEditorLogic'
import {
    CUSTOMER_ONBOARDING_AND_RETENTION_WORKFLOW_ID,
    workflowEditorStoryDecorator,
} from '../workflowEditorStoryFixtures'

const meta: Meta<typeof Workflow> = {
    title: 'Products/Workflows/Editor/Graph',
    component: Workflow,
    parameters: {
        layout: 'fullscreen',
        mockDate: '2026-09-04 12:00:00',
        testOptions: {
            waitForLoadersToDisappear: true,
            waitForSelector: '[data-attr=workflow-editor]',
            viewport: { width: 1600, height: 1000 },
        },
    },
    decorators: [workflowEditorStoryDecorator],
}
export default meta

function StorybookGraphViewport({ id }: { id: string }): null {
    const { nodes } = useValues(hogFlowEditorLogic({ id }))
    const { fitView } = useActions(hogFlowEditorLogic({ id }))

    useEffect(() => {
        if (nodes.length === 0) {
            return
        }
        const frame = requestAnimationFrame(() => fitView({ duration: 0 }))
        return () => cancelAnimationFrame(frame)
    }, [fitView, nodes])

    return null
}

const WorkflowStory = ({ id }: { id: string }): JSX.Element => (
    <BindLogic logic={workflowLogic} props={{ id }}>
        <div className="h-screen [&>div]:!h-full [&>div]:!max-h-none">
            <Workflow id={id} />
            <StorybookGraphViewport id={id} />
        </div>
    </BindLogic>
)

export const NewWorkflow: StoryFn = () => <WorkflowStory id="new" />
export const CustomerOnboardingAndRetention: StoryFn = () => (
    <WorkflowStory id={CUSTOMER_ONBOARDING_AND_RETENTION_WORKFLOW_ID} />
)
export const SupportSlaRouting: StoryFn = () => <WorkflowStory id="example-support-sla-routing" />
export const RenewalWindowAlerts: StoryFn = () => <WorkflowStory id="example-renewal-window-alerts" />
export const PendingTicketCleanup: StoryFn = () => <WorkflowStory id="example-pending-ticket-cleanup" />
export const AddOnPromotionEmails: StoryFn = () => <WorkflowStory id="example-add-on-promotion-emails" />
