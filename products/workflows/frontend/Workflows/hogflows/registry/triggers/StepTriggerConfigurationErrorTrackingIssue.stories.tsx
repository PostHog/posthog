import { Meta, StoryFn } from '@storybook/react'
import { BindLogic, useActions } from 'kea'
import { useEffect } from 'react'

import { PropertyFilterType, PropertyOperator } from '~/types'

import { WorkflowLogicProps, workflowLogic } from '../../../workflowLogic'
import { HogFlowAction } from '../../types'
import { StepTriggerConfigurationErrorTrackingIssue } from './StepTriggerConfigurationErrorTrackingIssue'

type TriggerAction = Extract<HogFlowAction, { type: 'trigger' }>
const LOGIC_PROPS: WorkflowLogicProps = { id: 'new' }

const meta: Meta<typeof StepTriggerConfigurationErrorTrackingIssue> = {
    title: 'Products/Workflows/Steps/Error tracking issue created',
    component: StepTriggerConfigurationErrorTrackingIssue,
}
export default meta

function triggerAction(properties: NonNullable<TriggerAction['filters']>['properties']): TriggerAction {
    return {
        id: 'trigger_1',
        type: 'trigger',
        name: 'Trigger',
        description: '',
        config: {
            type: 'internal-event',
            filters: {
                source: 'internal-events',
                events: [{ id: '$error_tracking_issue_created', type: 'events', name: 'Issue created' }],
                properties,
            },
        },
    }
}

const Template: StoryFn<{ action: TriggerAction }> = ({ action }) => {
    const { setWorkflowInfo } = useActions(workflowLogic(LOGIC_PROPS))

    useEffect(() => {
        setWorkflowInfo({ actions: [action] })
    }, [action, setWorkflowInfo])

    return (
        <BindLogic logic={workflowLogic} props={LOGIC_PROPS}>
            <div className="w-full max-w-xl p-4">
                <StepTriggerConfigurationErrorTrackingIssue node={{ data: action }} />
            </div>
        </BindLogic>
    )
}

export const AllNewIssues = Template.bind({})
AllNewIssues.args = { action: triggerAction([]) }

export const FilteredIssues = Template.bind({})
FilteredIssues.args = {
    action: triggerAction([
        { key: 'severity', type: PropertyFilterType.Event, operator: PropertyOperator.Exact, value: ['high'] },
    ]),
}
