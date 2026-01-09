import api from 'lib/api'
import { CyclotronJobInputsValidation } from 'lib/components/CyclotronJob/CyclotronJobInputsValidation'
import { LiquidRenderer } from 'lib/utils/liquid'
import { sanitizeInputs } from 'scenes/hog-functions/configuration/hogFunctionConfigurationLogic'
import { EmailTemplate } from 'scenes/hog-functions/email-templater/emailTemplaterLogic'

import { HogFunctionTemplateType } from '~/types'

import { HogFlowActionSchema, isFunctionAction, isTriggerFunction } from './hogflows/steps/types'
import { type HogFlow, HogFlowActionValidationResult } from './hogflows/types'

// Core workflow structure that both workflows and templates share
// This represents the shared structure (actions, edges, trigger, etc.) without status/scope/image_url
// TODOdin: Better name for this type
export type WorkflowCore = Omit<HogFlow, 'status'>

function getTemplatingError(value: string, templating?: 'liquid' | 'hog'): string | undefined {
    if (templating === 'liquid' && typeof value === 'string') {
        try {
            LiquidRenderer.parse(value)
        } catch (e: any) {
            return `Liquid template error: ${e.message}`
        }
    }
}

export function sanitizeWorkflowCore(
    workflow: WorkflowCore,
    hogFunctionTemplatesById: Record<string, HogFunctionTemplateType>
): WorkflowCore {
    // Sanitize all function-like actions the same as we would a hog function
    workflow.actions.forEach((action) => {
        if (isFunctionAction(action) || isTriggerFunction(action)) {
            const inputs = action.config.inputs
            const template = hogFunctionTemplatesById[action.config.template_id]
            if (template) {
                action.config.inputs = sanitizeInputs({
                    inputs_schema: template.inputs_schema,
                    inputs: inputs,
                })
            }
        }
    })
    return workflow
}

export function getActionValidationErrors(
    workflow: WorkflowCore,
    hogFunctionTemplatesById: Record<string, HogFunctionTemplateType>
): Record<string, HogFlowActionValidationResult | null> {
    return workflow.actions.reduce(
        (acc, action) => {
            const result: HogFlowActionValidationResult = {
                valid: true,
                schema: null,
                errors: {},
            }
            const schemaValidation = HogFlowActionSchema.safeParse(action)

            if (!schemaValidation.success) {
                result.valid = false
                result.schema = schemaValidation.error
            } else if (action.type === 'function_email') {
                // special case for function_email which has nested email inputs, so basic hog input validation is not enough
                // TODO: modify email/native_email input type to flatten email inputs so we don't need this special case
                const emailValue = action.config.inputs?.email?.value as any | undefined
                const emailTemplating = action.config.inputs?.email?.templating

                const emailTemplateErrors: Partial<EmailTemplate> = {
                    html: !emailValue?.html
                        ? 'HTML is required'
                        : getTemplatingError(emailValue?.html, emailTemplating),
                    subject: !emailValue?.subject
                        ? 'Subject is required'
                        : getTemplatingError(emailValue?.subject, emailTemplating),
                    from: !emailValue?.from?.email
                        ? 'From is required'
                        : getTemplatingError(emailValue?.from?.email, emailTemplating),
                    to: !emailValue?.to?.email
                        ? 'To is required'
                        : getTemplatingError(emailValue?.to?.email, emailTemplating),
                }

                const combinedErrors = Object.values(emailTemplateErrors)
                    .filter((v) => !!v)
                    .join(', ')

                if (combinedErrors) {
                    result.valid = false
                    result.errors = {
                        email: combinedErrors,
                    }
                }
            }

            if (isFunctionAction(action) || isTriggerFunction(action)) {
                const template = hogFunctionTemplatesById[action.config.template_id]
                if (!template) {
                    result.valid = false
                    result.errors = {
                        // This is a special case for the template_id field which might need to go to a generic error message
                        _template_id: 'Template not found',
                    }
                } else {
                    const configValidation = CyclotronJobInputsValidation.validate(
                        action.config.inputs,
                        template.inputs_schema ?? []
                    )
                    result.valid = configValidation.valid
                    result.errors = configValidation.errors
                }
            }

            if (action.type === 'trigger') {
                // custom validation here that we can't easily express in the schema
                if (action.config.type === 'event') {
                    if (!action.config.filters.events?.length && !action.config.filters.actions?.length) {
                        result.valid = false
                        result.errors = {
                            filters: 'At least one event or action is required',
                        }
                    }
                } else if (action.config.type === 'schedule') {
                    if (!action.config.scheduled_at) {
                        result.valid = false
                        result.errors = {
                            scheduled_at: 'A scheduled time is required',
                        }
                    }
                } else if (action.config.type === 'batch') {
                    if (!action.config.filters.properties?.length) {
                        result.valid = false
                        result.errors = {
                            filters: 'At least one property filter is required for batch workflows',
                        }
                    }
                }
            }

            acc[action.id] = result
            return acc
        },
        {} as Record<string, HogFlowActionValidationResult>
    )
}

export async function loadHogFunctionTemplatesById(): Promise<Record<string, HogFunctionTemplateType>> {
    const allTemplates = await api.hogFunctions.listTemplates({
        types: ['destination', 'source_webhook'],
    })

    const allTemplatesById = allTemplates.results.reduce(
        (acc, template) => {
            acc[template.id] = template
            return acc
        },
        {} as Record<string, HogFunctionTemplateType>
    )

    return allTemplatesById
}

export interface TemplateFormDefaults {
    name: string
    description: string
    image_url: string | null
    scope: 'team' | 'global'
}

export function getDefaultTemplateFormValues(
    name: string = '',
    description: string = '',
    image_url: string | null = null
): TemplateFormDefaults {
    return {
        name,
        description,
        image_url,
        scope: 'team',
    }
}

export function determineTemplateScope(
    userIsStaff: boolean | undefined,
    requestedScope?: 'team' | 'global'
): 'team' | 'global' {
    if (userIsStaff && requestedScope) {
        return requestedScope
    }
    return 'team'
}
