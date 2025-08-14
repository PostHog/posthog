import { afterMount, kea, key, listeners, path, props, selectors } from 'kea'
import { forms } from 'kea-forms'
import { loaders } from 'kea-loaders'
import api from 'lib/api'
import { HogFunctionTemplateType } from '~/types'

import type { hogFunctionStepLogicType } from './hogFunctionStepLogicType'
import { HogFlowAction } from '../types'
import { Node } from '@xyflow/react'
import { templateToConfiguration } from 'scenes/hog-functions/configuration/hogFunctionConfigurationLogic'
import { LiquidRenderer } from 'lib/utils/liquid'
import { EmailTemplate } from 'scenes/hog-functions/email-templater/emailTemplaterLogic'

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
    forms(({ props, values }) => ({
        configuration: {
            defaults: {
                inputs: props.node?.data.config.inputs,
                inputs_schema: [],
            },
            alwaysShowErrors: true,
            showErrorsOnTouch: true,
            errors: () => {
                return {
                    ...(values.inputFormErrors as any),
                }
            },
        },
    })),

    selectors(() => ({
        inputFormErrors: [
            (s) => [s.configuration, s.template],
            (configuration, template) => {
                const inputs = configuration.inputs ?? {}
                const inputErrors: Record<string, string> = {}

                template?.inputs_schema?.forEach((inputSchema) => {
                    const key = inputSchema.key
                    const input = inputs[key]
                    const language = input?.templating ?? 'hog'
                    const value = input?.value
                    if (input?.secret) {
                        // We leave unmodified secret values alone
                        return
                    }

                    const getTemplatingError = (value: string): string | undefined => {
                        if (language === 'liquid' && typeof value === 'string') {
                            try {
                                LiquidRenderer.parse(value)
                            } catch (e: any) {
                                return `Liquid template error: ${e.message}`
                            }
                        }
                    }

                    const addTemplatingError = (value: string): void => {
                        const templatingError = getTemplatingError(value)
                        if (templatingError) {
                            inputErrors[key] = templatingError
                        }
                    }

                    const missing = value === undefined || value === null || value === ''
                    if (inputSchema.required && missing) {
                        inputErrors[key] = 'This field is required'
                    }

                    if (inputSchema.type === 'json' && typeof value === 'string') {
                        try {
                            JSON.parse(value)
                        } catch {
                            inputErrors[key] = 'Invalid JSON'
                        }

                        addTemplatingError(value)
                    }

                    if (['email', 'native_email'].includes(inputSchema.type) && value) {
                        const emailTemplateErrors: Partial<EmailTemplate> = {
                            html: !value.html ? 'HTML is required' : getTemplatingError(value.html),
                            subject: !value.subject ? 'Subject is required' : getTemplatingError(value.subject),
                            from: !value.from ? 'From is required' : getTemplatingError(value.from),
                            to: !value.to.email ? 'To is required' : getTemplatingError(value.to),
                        }

                        const combinedErrors = Object.values(emailTemplateErrors)
                            .filter((v) => !!v)
                            .join(', ')

                        if (combinedErrors) {
                            inputErrors[key] = combinedErrors
                        }
                    }

                    if (inputSchema.type === 'string' && typeof value === 'string') {
                        addTemplatingError(value)
                    }

                    if (inputSchema.type === 'dictionary') {
                        for (const val of Object.values(value ?? {})) {
                            if (typeof val === 'string') {
                                addTemplatingError(val)
                            }
                        }
                    }
                })

                return Object.keys(inputErrors).length > 0
                    ? {
                          inputs: inputErrors,
                      }
                    : null
            },
        ],
    })),

    listeners(({ actions, values }) => ({
        loadTemplateSuccess: ({ template }) => {
            // Set the inputs to be the defaults if not already set
            if (template && Object.keys(values.configuration.inputs ?? {}).length === 0) {
                actions.setConfigurationValues({
                    inputs: templateToConfiguration(template).inputs ?? {},
                })
            }
        },
    })),
    afterMount(({ props, actions }) => {
        if (props.node?.data.config.template_id) {
            actions.loadTemplate()
        }
    }),
])
