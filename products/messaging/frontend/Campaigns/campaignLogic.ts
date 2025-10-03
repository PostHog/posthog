import { actions, afterMount, kea, key, listeners, path, props, selectors } from 'kea'
import { DeepPartialMap, ValidationErrorType, forms } from 'kea-forms'
import { lazyLoaders, loaders } from 'kea-loaders'
import { router } from 'kea-router'

import { LemonDialog } from '@posthog/lemon-ui'

import api from 'lib/api'
import { CyclotronJobInputsValidation } from 'lib/components/CyclotronJob/CyclotronJobInputsValidation'
import { lemonToast } from 'lib/lemon-ui/LemonToast'
import { LiquidRenderer } from 'lib/utils/liquid'
import { sanitizeInputs } from 'scenes/hog-functions/configuration/hogFunctionConfigurationLogic'
import { EmailTemplate } from 'scenes/hog-functions/email-templater/emailTemplaterLogic'
import { urls } from 'scenes/urls'

import { HogFunctionTemplateType } from '~/types'

import type { campaignLogicType } from './campaignLogicType'
import { campaignSceneLogic } from './campaignSceneLogic'
import { HogFlowActionSchema, isFunctionAction, isTriggerFunction } from './hogflows/steps/types'
import { type HogFlow, type HogFlowAction, HogFlowActionValidationResult, type HogFlowEdge } from './hogflows/types'

export interface CampaignLogicProps {
    id?: string
}

export const TRIGGER_NODE_ID = 'trigger_node'
export const EXIT_NODE_ID = 'exit_node'

export type TriggerAction = Extract<HogFlowAction, { type: 'trigger' }>

const NEW_CAMPAIGN: HogFlow = {
    id: 'new',
    name: 'New campaign',
    actions: [
        {
            id: TRIGGER_NODE_ID,
            type: 'trigger',
            name: 'Trigger',
            description: 'User performs an action to start the campaign.',
            created_at: 0,
            updated_at: 0,
            config: {
                type: 'event',
                filters: {},
            },
        },
        {
            id: EXIT_NODE_ID,
            type: 'exit',
            name: 'Exit',
            description: 'User moved through the campaign without errors.',
            config: {
                reason: 'Default exit',
            },
            created_at: 0,
            updated_at: 0,
        },
    ],
    edges: [
        {
            from: TRIGGER_NODE_ID,
            to: EXIT_NODE_ID,
            type: 'continue',
        },
    ],
    conversion: { window_minutes: 0, filters: [] },
    exit_condition: 'exit_only_at_end',
    version: 1,
    status: 'draft',
    team_id: -1,
    created_at: '',
    updated_at: '',
}

function getTemplatingError(value: string, templating?: 'liquid' | 'hog'): string | undefined {
    if (templating === 'liquid' && typeof value === 'string') {
        try {
            LiquidRenderer.parse(value)
        } catch (e: any) {
            return `Liquid template error: ${e.message}`
        }
    }
}

export function sanitizeCampaign(
    campaign: HogFlow,
    hogFunctionTemplatesById: Record<string, HogFunctionTemplateType>
): HogFlow {
    // Sanitize all function-like actions the same as we would a hog function
    campaign.actions.forEach((action) => {
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
    return campaign
}

export const campaignLogic = kea<campaignLogicType>([
    path(['products', 'messaging', 'frontend', 'Campaigns', 'campaignLogic']),
    props({ id: 'new' } as CampaignLogicProps),
    key((props) => props.id || 'new'),
    actions({
        partialSetCampaignActionConfig: (actionId: string, config: Partial<HogFlowAction['config']>) => ({
            actionId,
            config,
        }),
        setCampaignActionConfig: (actionId: string, config: HogFlowAction['config']) => ({ actionId, config }),
        setCampaignAction: (actionId: string, action: HogFlowAction) => ({ actionId, action }),
        setCampaignActionEdges: (actionId: string, edges: HogFlow['edges']) => ({ actionId, edges }),
        // NOTE: This is a wrapper for setCampaignValues, to get around some weird typegen issues
        setCampaignInfo: (campaign: Partial<HogFlow>) => ({ campaign }),
        saveCampaignPartial: (campaign: Partial<HogFlow>) => ({ campaign }),
        discardChanges: true,
    }),
    loaders(({ props, values }) => ({
        originalCampaign: [
            null as HogFlow | null,
            {
                loadCampaign: async () => {
                    if (!props.id || props.id === 'new') {
                        return { ...NEW_CAMPAIGN }
                    }

                    return api.hogFlows.getHogFlow(props.id)
                },
                saveCampaign: async (updates: HogFlow) => {
                    updates = sanitizeCampaign(updates, values.hogFunctionTemplatesById)

                    if (!props.id || props.id === 'new') {
                        return api.hogFlows.createHogFlow(updates)
                    }

                    return api.hogFlows.updateHogFlow(props.id, updates)
                },
            },
        ],
    })),
    lazyLoaders(() => ({
        hogFunctionTemplatesById: [
            {} as Record<string, HogFunctionTemplateType>,
            {
                loadHogFunctionTemplatesById: async () => {
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
                },
            },
        ],
    })),
    forms(({ actions, values }) => ({
        campaign: {
            defaults: NEW_CAMPAIGN,
            errors: ({ name, actions }) => {
                const errors = {
                    name: !name ? 'Name is required' : undefined,
                    actions: actions.some((action) => !(values.actionValidationErrorsById[action.id]?.valid ?? true))
                        ? 'Some fields need work'
                        : undefined,
                } as DeepPartialMap<HogFlow, ValidationErrorType>

                return errors
            },
            submit: async (values) => {
                if (!values) {
                    return
                }

                actions.saveCampaign(values)
            },
        },
    })),

    selectors({
        logicProps: [() => [(_, props) => props], (props): CampaignLogicProps => props],
        campaignLoading: [(s) => [s.originalCampaignLoading], (originalCampaignLoading) => originalCampaignLoading],
        edgesByActionId: [
            (s) => [s.campaign],
            (campaign): Record<string, HogFlowEdge[]> => {
                return campaign.edges.reduce(
                    (acc, edge) => {
                        if (!acc[edge.from]) {
                            acc[edge.from] = []
                        }
                        acc[edge.from].push(edge)

                        if (!acc[edge.to]) {
                            acc[edge.to] = []
                        }
                        acc[edge.to].push(edge)

                        return acc
                    },
                    {} as Record<string, HogFlowEdge[]>
                )
            },
        ],

        actionValidationErrorsById: [
            (s) => [s.campaign, s.hogFunctionTemplatesById],
            (campaign, hogFunctionTemplatesById): Record<string, HogFlowActionValidationResult | null> => {
                return campaign.actions.reduce(
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
                        } else if (isFunctionAction(action) || isTriggerFunction(action)) {
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
                        } else if (action.type === 'trigger') {
                            // custom validation here that we can't easily express in the schema
                            if (action.config.type === 'event') {
                                if (!action.config.filters.events?.length && !action.config.filters.actions?.length) {
                                    result.valid = false
                                    result.errors = {
                                        filters: 'At least one event or action is required',
                                    }
                                }
                            }
                        }

                        acc[action.id] = result
                        return acc
                    },
                    {} as Record<string, HogFlowActionValidationResult>
                )
            },
        ],

        triggerAction: [
            (s) => [s.campaign],
            (campaign): TriggerAction | null => {
                return (campaign.actions.find((action) => action.type === 'trigger') as TriggerAction) ?? null
            },
        ],

        campaignSanitized: [
            (s) => [s.campaign, s.hogFunctionTemplatesById],
            (campaign, hogFunctionTemplatesById): HogFlow => {
                return sanitizeCampaign(campaign, hogFunctionTemplatesById)
            },
        ],
    }),
    listeners(({ actions, values, props }) => ({
        saveCampaignPartial: async ({ campaign }) => {
            actions.saveCampaign({
                ...values.campaign,
                ...campaign,
            })
        },
        loadCampaignSuccess: async ({ originalCampaign }) => {
            actions.resetCampaign(originalCampaign)
        },
        saveCampaignSuccess: async ({ originalCampaign }) => {
            lemonToast.success('Campaign saved')
            if (props.id === 'new' && originalCampaign.id) {
                router.actions.replace(
                    urls.messagingCampaign(originalCampaign.id, campaignSceneLogic.findMounted()?.values.currentTab)
                )
            }

            actions.resetCampaign(originalCampaign)
        },
        discardChanges: () => {
            if (!values.originalCampaign) {
                return
            }

            LemonDialog.open({
                title: 'Discard changes',
                description: 'Are you sure?',
                primaryButton: {
                    children: 'Discard',
                    onClick: () => actions.resetCampaign(values.originalCampaign ?? NEW_CAMPAIGN),
                },
                secondaryButton: {
                    children: 'Cancel',
                },
            })
        },
        setCampaignInfo: async ({ campaign }) => {
            actions.setCampaignValues(campaign)
        },
        setCampaignActionConfig: async ({ actionId, config }) => {
            const action = values.campaign.actions.find((action) => action.id === actionId)
            if (!action) {
                return
            }

            action.config = { ...config } as HogFlowAction['config']
            actions.setCampaignValues({ actions: [...values.campaign.actions] })
        },
        partialSetCampaignActionConfig: async ({ actionId, config }) => {
            const action = values.campaign.actions.find((action) => action.id === actionId)
            if (!action) {
                return
            }

            actions.setCampaignActionConfig(actionId, { ...action.config, ...config } as HogFlowAction['config'])
        },
        setCampaignAction: async ({ actionId, action }) => {
            const newActions = values.campaign.actions.map((a) => (a.id === actionId ? action : a))
            actions.setCampaignValues({ actions: newActions })
        },
        setCampaignActionEdges: async ({ actionId, edges }) => {
            // Helper method - Replaces all edges related to the action with the new edges
            const actionEdges = values.edgesByActionId[actionId] ?? []
            const newEdges = values.campaign.edges.filter((e) => !actionEdges.includes(e))

            actions.setCampaignValues({ edges: [...newEdges, ...edges] })
        },
    })),
    afterMount(({ actions }) => {
        actions.loadCampaign()
    }),
])
