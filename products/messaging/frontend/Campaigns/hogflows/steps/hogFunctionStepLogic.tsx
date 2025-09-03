import { Node } from '@xyflow/react'
import { kea, key, path, props, propsChanged } from 'kea'
import { forms } from 'kea-forms'

import { templateToConfiguration } from 'scenes/hog-functions/configuration/hogFunctionConfigurationLogic'

import { HogFunctionTemplateType } from '~/types'

import { HogFlowAction } from '../types'
import type { hogFunctionStepLogicType } from './hogFunctionStepLogicType'

export type StepFunctionNode = Node<
    Extract<
        HogFlowAction,
        | { type: 'function_email' }
        | { type: 'function_slack' }
        | { type: 'function_sms' }
        | { type: 'function_webhook' }
    >
>

export interface HogFunctionStepLogicProps {
    node?: StepFunctionNode
    template?: HogFunctionTemplateType
}

export const hogFunctionStepLogic = kea<hogFunctionStepLogicType>([
    path(['products', 'messaging', 'frontend', 'Campaigns', 'hogflows', 'steps']),
    props({} as HogFunctionStepLogicProps),
    key(({ node }: HogFunctionStepLogicProps) => `${node?.id}_${node?.data.config.template_id}`),
    forms(({ props }) => ({
        configuration: {
            defaults: {
                inputs: props.node?.data?.config?.inputs || {},
            },
        },
    })),

    propsChanged(({ actions, props, values }, oldProps) => {
        const { template } = props
        console.log('props changed', template, oldProps.template)
        console.log('template changed', template, values.configuration.inputs)
        if (template && Object.keys(values.configuration.inputs ?? {}).length === 0) {
            console.log('setting inputs', templateToConfiguration(template).inputs)
            actions.setConfigurationValues({
                inputs: templateToConfiguration(template).inputs ?? {},
            })
        }
    }),
])
