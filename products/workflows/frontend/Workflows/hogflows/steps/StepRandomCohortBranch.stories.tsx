import { Meta, StoryFn } from '@storybook/react'
import { Node } from '@xyflow/react'
import { BindLogic, useActions } from 'kea'
import { useEffect } from 'react'

import { WorkflowLogicProps, workflowLogic } from '../../workflowLogic'
import { hogFlowEditorLogic } from '../hogFlowEditorLogic'
import { HogFlowAction } from '../types'
import { StepRandomCohortBranchConfiguration } from './StepRandomCohortBranch'

type RandomCohortBranchAction = Extract<HogFlowAction, { type: 'random_cohort_branch' }>

const LOGIC_PROPS: WorkflowLogicProps = { id: 'new' }

const meta: Meta<typeof StepRandomCohortBranchConfiguration> = {
    title: 'Products/Workflows/Steps/Random cohort branch',
    component: StepRandomCohortBranchConfiguration,
}
export default meta

function branchAction(percentages: number[]): RandomCohortBranchAction {
    return {
        id: 'random_cohort_branch_1',
        type: 'random_cohort_branch',
        name: 'Split',
        description: 'Split people across cohorts.',
        config: { cohorts: percentages.map((percentage) => ({ percentage })) },
    } as RandomCohortBranchAction
}

const Template: StoryFn<{ action: RandomCohortBranchAction }> = ({ action }) => {
    const { setWorkflowInfo } = useActions(workflowLogic(LOGIC_PROPS))

    useEffect(() => {
        setWorkflowInfo({ actions: [action] })
    }, [action, setWorkflowInfo])

    return (
        <BindLogic logic={workflowLogic} props={LOGIC_PROPS}>
            <BindLogic logic={hogFlowEditorLogic} props={LOGIC_PROPS}>
                <div className="w-[420px] p-4 flex flex-col gap-2">
                    <StepRandomCohortBranchConfiguration node={{ data: action } as Node<RandomCohortBranchAction>} />
                </div>
            </BindLogic>
        </BindLogic>
    )
}

export const AddsUpToOneHundred: StoryFn<{ action: RandomCohortBranchAction }> = Template.bind({})
AddsUpToOneHundred.args = { action: branchAction([50, 50]) }

export const AddsUpToLessThanOneHundred: StoryFn<{ action: RandomCohortBranchAction }> = Template.bind({})
AddsUpToLessThanOneHundred.args = { action: branchAction([10, 10]) }

export const AddsUpToMoreThanOneHundred: StoryFn<{ action: RandomCohortBranchAction }> = Template.bind({})
AddsUpToMoreThanOneHundred.args = { action: branchAction([60, 60]) }

export const AddsUpToZero: StoryFn<{ action: RandomCohortBranchAction }> = Template.bind({})
AddsUpToZero.args = { action: branchAction([0, 0]) }
