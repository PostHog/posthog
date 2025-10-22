import { Node } from '@xyflow/react'
import { kea, key, path, props, propsChanged } from 'kea'
import { forms } from 'kea-forms'

import { templateToConfiguration } from 'scenes/hog-functions/configuration/hogFunctionConfigurationLogic'

import { HogFunctionTemplateType } from '~/types'

import { HogFlowAction } from '../types'
import type { hogFunctionStepLogicType } from './hogFunctionStepLogicType'

export type StepFunctionNode = Node<
    Extract<HogFlowAction, { type: 'function' } | { type: 'function_email' } | { type: 'function_sms' }>
>

export interface HogFunctionStepLogicProps {
    node?: StepFunctionNode
    template?: HogFunctionTemplateType
}

export const hogFunctionStepLogic = kea<hogFunctionStepLogicType>([
    path(['products', 'workflows', 'frontend', 'Workflows', 'hogflows', 'steps']),
    props({} as HogFunctionStepLogicProps),
    key(({ node }: HogFunctionStepLogicProps) => `${node?.id}_${node?.data.config.template_id}`),
    forms(({ props }) => ({
        configuration: {
            defaults: {
                inputs: props.node?.data?.config?.inputs || {},
            },
        },
    })),

    propsChanged(({ actions, props, values }) => {
        const { template } = props
        if (template && Object.keys(values.configuration.inputs ?? {}).length === 0) {
            actions.setConfigurationValues({
                inputs: templateToConfiguration(template).inputs ?? {},
            })
        }
    }),
])
