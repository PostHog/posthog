import { actions, connect, kea, path, props, reducers, selectors } from 'kea'

import { CyclotronJobInputSchemaType } from '~/types'

import { WorkflowLogicProps, workflowLogic } from '../workflowLogic'
import type { hogFlowManualTriggerButtonLogicType } from './HogFlowManualTriggerButtonLogicType'

const parseValue = (value: string, variableType: string): any => {
    if (value === '') {
        return undefined
    }
    switch (variableType) {
        case 'number':
            const num = Number(value)
            return isNaN(num) ? value : num
        case 'boolean':
            if (value.toLowerCase() === 'true') {
                return true
            }
            if (value.toLowerCase() === 'false') {
                return false
            }
            return value
        default:
            return value
    }
}

export const hogFlowManualTriggerButtonLogic = kea<hogFlowManualTriggerButtonLogicType>([
    path(['products', 'workflows', 'frontend', 'Workflows', 'hogflows', 'hogFlowManualTriggerButtonLogic']),
    props({} as WorkflowLogicProps),
    connect((props: WorkflowLogicProps) => ({
        values: [workflowLogic(props), ['workflow']],
        actions: [workflowLogic(props), ['triggerManualWorkflow']],
    })),
    actions({
        setInput: (key: string, value: string) => ({ key, value }),
        setPopoverVisible: (visible: boolean) => ({ visible }),
        clearInputs: () => ({}),
    }),
    reducers({
        inputs: [
            {} as Record<string, string>,
            {
                setInput: (state, { key, value }) => ({ ...state, [key]: value }),
                clearInputs: () => ({}),
            },
        ],
        popoverVisible: [
            false,
            {
                setPopoverVisible: (_, { visible }) => visible,
            },
        ],
    }),
    selectors({
        variableValues: [
            (s) => [s.inputs, s.workflow],
            (inputs: Record<string, string>, workflow: any): Record<string, any> => {
                if (!workflow?.variables) {
                    return {}
                }
                return Object.fromEntries(
                    workflow.variables.map((v: CyclotronJobInputSchemaType) => {
                        const inputValue = inputs[v.key]
                        if (inputValue !== undefined && inputValue !== '') {
                            // Parse the string input to the correct type
                            return [v.key, parseValue(inputValue, v.type)]
                        }
                        // Use default value as-is (preserve original type)
                        return [v.key, v.default]
                    })
                )
            },
        ],
    }),
])
