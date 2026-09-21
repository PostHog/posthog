import { Meta, StoryFn } from '@storybook/react'
import { Node } from '@xyflow/react'
import { BindLogic, useActions } from 'kea'
import { useEffect } from 'react'

import { FEATURE_FLAGS } from 'lib/constants'

import { WorkflowLogicProps, workflowLogic } from '../../workflowLogic'
import { hogFlowEditorLogic } from '../hogFlowEditorLogic'
import { HogFlowAction } from '../types'
import { StepDelayConfiguration } from './StepDelay'

type DelayAction = Extract<HogFlowAction, { type: 'delay' }>

const LOGIC_PROPS: WorkflowLogicProps = { id: 'new' }

const meta: Meta<typeof StepDelayConfiguration> = {
    title: 'Products/Workflows/Steps/Delay',
    component: StepDelayConfiguration,
    parameters: {
        // The stories show the panel an author sees once the date mode is rolled out
        featureFlags: [FEATURE_FLAGS.WORKFLOWS_DELAY_UNTIL_DATE],
    },
}
export default meta

function delayAction(config: DelayAction['config'], description: string): DelayAction {
    return {
        id: 'delay_1',
        type: 'delay',
        name: 'Delay',
        description,
        config,
    } as DelayAction
}

const Template: StoryFn<{ action: DelayAction }> = ({ action }) => {
    const { setWorkflowInfo } = useActions(workflowLogic(LOGIC_PROPS))

    useEffect(() => {
        setWorkflowInfo({ actions: [action] })
    }, [action, setWorkflowInfo])

    return (
        <BindLogic logic={workflowLogic} props={LOGIC_PROPS}>
            <BindLogic logic={hogFlowEditorLogic} props={LOGIC_PROPS}>
                <div className="w-[420px] p-4 flex flex-col gap-2">
                    <StepDelayConfiguration node={{ data: action } as Node<DelayAction>} />
                </div>
            </BindLogic>
        </BindLogic>
    )
}

export const FixedDuration: StoryFn<{ action: DelayAction }> = Template.bind({})
FixedDuration.args = { action: delayAction({ delay_duration: '10m' }, 'Wait for 10 minutes.') }

export const DateOnThePerson: StoryFn<{ action: DelayAction }> = Template.bind({})
DateOnThePerson.args = {
    action: delayAction(
        { delay_until: { expression: 'person.properties.trial_expires_at', offset: '-1d' } },
        'Wait until 1 day before trial_expires_at.'
    ),
}

export const DateNotChosenYet: StoryFn<{ action: DelayAction }> = Template.bind({})
DateNotChosenYet.args = {
    action: delayAction({ delay_until: { expression: '' } }, 'Wait until a date on the person or event.'),
}
