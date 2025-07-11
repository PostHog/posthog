import { afterMount, kea, key, path, props } from 'kea'
import { forms } from 'kea-forms'
import { loaders } from 'kea-loaders'
import api from 'lib/api'
import { HogFunctionTemplateType } from '~/types'

import type { hogFunctionStepLogicType } from './hogFunctionStepLogicType'
import { HogFlowAction } from '../types'
import { Node } from '@xyflow/react'

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
}

export const hogFunctionStepLogic = kea<hogFunctionStepLogicType>([
    path(['products', 'messaging', 'frontend', 'Campaigns', 'hogflows', 'steps']),
    props({} as HogFunctionStepLogicProps),
    key(({ node }: HogFunctionStepLogicProps) => `${node?.id}_${node?.data.config.template_id}`),
    loaders(({ props }) => ({
        template: [
            null as HogFunctionTemplateType | null,
            {
                loadTemplate: async () => {
                    const templateId = props.node?.data.config.template_id
                    if (!templateId) {
                        return null
                    }

                    const res = await api.hogFunctions.getTemplate(templateId)

                    if (!res) {
                        throw new Error('Template not found')
                    }
                    return res
                },
            },
        ],
    })),
    forms(({ props }) => ({
        configuration: {
            defaults: {
                inputs: props.node?.data.config.inputs || {},
            },
        },
    })),
    afterMount(({ props, actions }) => {
        if (props.node?.data.config.template_id) {
            actions.loadTemplate()
        }
    }),
])
