import { Node } from '@xyflow/react'
import { useActions } from 'kea'

import { workflowLogic } from '../../workflowLogic'
import { HogFlowAction } from '../types'
import { HogFlowDuration } from './components/HogFlowDuration'
import { StepSchemaErrors } from './components/StepSchemaErrors'

export function getDelayDescription(duration: string): string {
    const DURATION_REGEX = /^(\d*\.?\d+)([dhm])$/

    const parts = duration.match(DURATION_REGEX) ?? ['', '10', 'm']
    const [, numberValueString, unit] = parts
    const number = parseFloat(numberValueString)
    const unitLabel = unit === 'm' ? 'minute' : unit === 'h' ? 'hour' : 'day'
    const durationText = `${number} ${unitLabel}${number !== 1 ? 's' : ''}`

    return `Wait for ${durationText}.`
}

function shouldAutoUpdateDescription(description: string): boolean {
    const AUTO_DESCRIPTION_REGEX = /^Wait for \d+\.?\d* (minute|hour|day)s?\.$/
    const legacyDefaultDescription = 'Wait for a specified duration.'

    return (
        description.trim() === '' ||
        AUTO_DESCRIPTION_REGEX.test(description) ||
        description === legacyDefaultDescription
    )
}

export function StepDelayConfiguration({
    node,
}: {
    node: Node<Extract<HogFlowAction, { type: 'delay' }>>
}): JSX.Element {
    const action = node.data
    const { delay_duration } = action.config

    const { setWorkflowActionConfig, setWorkflowAction } = useActions(workflowLogic)

    return (
        <>
            <StepSchemaErrors />

            <p className="mb-0">Wait for a specified duration.</p>
            <HogFlowDuration
                value={delay_duration}
                onChange={(value) => {
                    setWorkflowActionConfig(action.id, { delay_duration: value })
                    if (shouldAutoUpdateDescription(action.description)) {
                        setWorkflowAction(action.id, { ...action, description: getDelayDescription(value) })
                    }
                }}
            />
        </>
    )
}
