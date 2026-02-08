import { actions, connect, kea, key, listeners, path, props } from 'kea'

import { WorkflowLogicProps, workflowLogic } from '../../workflowLogic'
import type { stepDelayLogicType } from './stepDelayLogicType'

const DURATION_REGEX = /^(\d*\.?\d+)([dhm])$/
const AUTO_DESCRIPTION_REGEX = /^Wait for \d*\.?\d+ (minute|hour|day)s?\.$/
const LEGACY_DEFAULT_DESCRIPTION = 'Wait for a specified duration.'

export function getDelayDescription(duration: string): string {
    const parts = duration.match(DURATION_REGEX) ?? ['', '10', 'm']
    const [, numberValueString, unit] = parts
    const number = parseFloat(numberValueString)
    const unitLabel = unit === 'm' ? 'minute' : unit === 'h' ? 'hour' : 'day'
    const durationText = `${number} ${unitLabel}${number !== 1 ? 's' : ''}`
    return `Wait for ${durationText}.`
}

export function shouldAutoUpdateDescription(description: string): boolean {
    return (
        description.trim() === '' ||
        AUTO_DESCRIPTION_REGEX.test(description) ||
        description === LEGACY_DEFAULT_DESCRIPTION
    )
}

export type StepDelayLogicProps = {
    workflowLogicProps: WorkflowLogicProps
}

export const stepDelayLogic = kea<stepDelayLogicType>([
    path((key) => ['products', 'workflows', 'frontend', 'Workflows', 'hogflows', 'steps', 'stepDelayLogic', key]),
    props({} as StepDelayLogicProps),
    key(({ workflowLogicProps }: StepDelayLogicProps) => workflowLogicProps.id || 'new'),
    connect(({ workflowLogicProps }: StepDelayLogicProps) => ({
        values: [workflowLogic(workflowLogicProps), ['workflow']],
        actions: [workflowLogic(workflowLogicProps), ['setWorkflowActionConfig', 'setWorkflowAction']],
    })),
    actions({
        setDelayWorkflowActionConfig: (actionId: string, config: { delay_duration: string }) => ({ actionId, config }),
    }),
    listeners(({ values, actions }) => ({
        setDelayWorkflowActionConfig: ({ actionId, config }) => {
            actions.setWorkflowActionConfig(actionId, config)

            const action = values.workflow.actions.find((a) => a.id === actionId)
            if (!action || action.type !== 'delay') {
                return
            }

            const delayConfig = config as { delay_duration: string }
            if (shouldAutoUpdateDescription(action.description)) {
                actions.setWorkflowAction(actionId, {
                    ...action,
                    description: getDelayDescription(delayConfig.delay_duration),
                })
            }
        },
    })),
])
