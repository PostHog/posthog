import { actions, afterMount, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import { lemonToast } from '@posthog/lemon-ui'

import api from 'lib/api'
import {
    HOG_FUNCTION_SUB_TEMPLATES,
    HOG_FUNCTION_SUB_TEMPLATE_COMMON_PROPERTIES,
} from 'scenes/hog-functions/sub-templates/sub-templates'

import { CyclotronJobInputType, HogFunctionSubTemplateIdType, HogFunctionTemplateType, HogFunctionType } from '~/types'

import type { errorTrackingAlertWizardLogicType } from './errorTrackingAlertWizardLogicType'

export type WizardDestinationKey = 'slack' | 'discord' | 'github' | 'microsoft-teams' | 'linear'
export type WizardTriggerKey = 'error-tracking-issue-created' | 'error-tracking-issue-reopened'
export type WizardStep = 'destination' | 'trigger' | 'configure'
export type AlertCreationView = 'none' | 'wizard' | 'traditional'

export const SUB_TEMPLATE_IDS: HogFunctionSubTemplateIdType[] = [
    'error-tracking-issue-created',
    'error-tracking-issue-reopened',
    'error-tracking-issue-spiking',
]

export interface WizardDestination {
    key: WizardDestinationKey
    name: string
    description: string
    icon: string
    templateId: string
}

const ALL_DESTINATIONS: WizardDestination[] = [
    {
        key: 'slack',
        name: 'Slack',
        description: 'Send a message to a channel',
        icon: '/static/services/slack.png',
        templateId: 'template-slack',
    },
    {
        key: 'discord',
        name: 'Discord',
        description: 'Post a notification via webhook',
        icon: '/static/services/discord.png',
        templateId: 'template-discord',
    },
    {
        key: 'github',
        name: 'GitHub',
        description: 'Create an issue in a repository',
        icon: '/static/services/github.png',
        templateId: 'template-github',
    },
    {
        key: 'microsoft-teams',
        name: 'Microsoft Teams',
        description: 'Send a message to a channel',
        icon: '/static/services/microsoft-teams.png',
        templateId: 'template-microsoft-teams',
    },
    {
        key: 'linear',
        name: 'Linear',
        description: 'Create an issue in a project',
        icon: '/static/services/linear.png',
        templateId: 'template-linear',
    },
]

const DESTINATIONS_DEFAULT_PRIORITY: WizardDestinationKey[] = [
    'slack',
    'discord',
    'github',
    'microsoft-teams',
    'linear',
]

export interface WizardTrigger {
    key: WizardTriggerKey
    name: string
    description: string
}

export const TRIGGER_OPTIONS: WizardTrigger[] = [
    {
        key: 'error-tracking-issue-created',
        name: 'Issue created',
        description: 'Get notified when a new error issue is detected',
    },
    {
        key: 'error-tracking-issue-reopened',
        name: 'Issue reopened',
        description: 'Get notified when a previously resolved issue comes back',
    },
]

function extractDestinationKeyFromAlert(alert: HogFunctionType): WizardDestinationKey | null {
    const templateId = alert.template?.id
    if (!templateId) {
        return null
    }
    for (const destination of ALL_DESTINATIONS) {
        if (templateId.startsWith(destination.templateId)) {
            return destination.key
        }
    }
    return null
}

export const errorTrackingAlertWizardLogic = kea<errorTrackingAlertWizardLogicType>([
    path(['products', 'error_tracking', 'frontend', 'alerting', 'errorTrackingAlertWizardLogic']),

    actions({
        setAlertCreationView: (view: AlertCreationView) => ({ view }),
        setStep: (step: WizardStep) => ({ step }),
        setDestinationKey: (destinationKey: WizardDestinationKey) => ({ destinationKey }),
        setTriggerKey: (triggerKey: WizardTriggerKey) => ({ triggerKey }),
        setInputValue: (key: string, value: CyclotronJobInputType) => ({ key, value }),
        resetWizard: true,
        createAlertSuccess: true,
        submitConfiguration: true,
    }),

    reducers({
        alertCreationView: [
            'none' as AlertCreationView,
            {
                setAlertCreationView: (_, { view }) => view,
                createAlertSuccess: () => 'none' as AlertCreationView,
            },
        ],
        currentStep: [
            'destination' as WizardStep,
            {
                setStep: (_, { step }) => step,
                setDestinationKey: () => 'trigger' as WizardStep,
                resetWizard: () => 'destination' as WizardStep,
            },
        ],
        selectedDestinationKey: [
            null as WizardDestinationKey | null,
            {
                setDestinationKey: (_, { destinationKey }) => destinationKey,
                resetWizard: () => null,
            },
        ],
        selectedTriggerKey: [
            null as WizardTriggerKey | null,
            {
                setTriggerKey: (_, { triggerKey }) => triggerKey,
                resetWizard: () => null,
            },
        ],
        alertCreated: [
            false,
            {
                createAlertSuccess: () => true,
                resetWizard: () => false,
            },
        ],
        inputValues: [
            {} as Record<string, CyclotronJobInputType>,
            {
                setInputValue: (state, { key, value }) => ({ ...state, [key]: value }),
                resetWizard: () => ({}),
                // Reset inputs when switching destination or trigger
                setDestinationKey: () => ({}),
                setTriggerKey: () => ({}),
            },
        ],
        submitting: [
            false,
            {
                submitConfiguration: () => true,
                createAlertSuccess: () => false,
            },
        ],
    }),

    loaders({
        existingAlerts: [
            [] as HogFunctionType[],
            {
                loadExistingAlerts: async () => {
                    const errorTrackingFilters = [
                        HOG_FUNCTION_SUB_TEMPLATE_COMMON_PROPERTIES['error-tracking-issue-created'].filters,
                        HOG_FUNCTION_SUB_TEMPLATE_COMMON_PROPERTIES['error-tracking-issue-reopened'].filters,
                    ].filter(Boolean)

                    const response = await api.hogFunctions.list({
                        types: ['internal_destination'],
                        filter_groups: errorTrackingFilters as any[],
                        limit: 100,
                    })

                    // TODO: REMOVE THIS ON PROD
                    await new Promise((resolve) => setTimeout(resolve, 1_000))

                    return response.results
                },
            },
        ],
        selectedTemplate: [
            null as HogFunctionTemplateType | null,
            {
                loadTemplate: async (templateId: string) => {
                    return await api.hogFunctions.getTemplate(templateId)
                },
            },
        ],
    }),

    selectors({
        usedDestinationKeys: [
            (s) => [s.existingAlerts],
            (existingAlerts): Set<WizardDestinationKey> => {
                const usedDestinationKeys = new Set<WizardDestinationKey>()
                for (const alert of existingAlerts) {
                    const destinationKey = extractDestinationKeyFromAlert(alert)
                    if (destinationKey) {
                        usedDestinationKeys.add(destinationKey)
                    }
                }
                return usedDestinationKeys
            },
        ],

        destinations: [
            (s) => [s.usedDestinationKeys],
            (usedDestinationKeys): WizardDestination[] => {
                const sorted = [...DESTINATIONS_DEFAULT_PRIORITY].sort((a, b) => {
                    const aUsed = usedDestinationKeys.has(a) ? 1 : 0
                    const bUsed = usedDestinationKeys.has(b) ? 1 : 0
                    return bUsed - aUsed
                })
                const top3 = sorted.slice(0, 3)
                return top3.map((destinationKey) => ALL_DESTINATIONS.find((d) => d.key === destinationKey)!)
            },
        ],

        activeSubTemplate: [
            (s) => [s.selectedDestinationKey, s.selectedTriggerKey],
            (selectedDestinationKey, selectedTriggerKey) => {
                if (!selectedDestinationKey || !selectedTriggerKey) {
                    return null
                }
                const destination = ALL_DESTINATIONS.find((d) => d.key === selectedDestinationKey)
                if (!destination) {
                    return null
                }
                const subTemplates = HOG_FUNCTION_SUB_TEMPLATES[selectedTriggerKey as HogFunctionSubTemplateIdType]
                return subTemplates?.find((t) => t.template_id === destination.templateId) ?? null
            },
        ],

        requiredInputsSchema: [
            (s) => [s.selectedTemplate, s.activeSubTemplate],
            (selectedTemplate, activeSubTemplate) => {
                if (!selectedTemplate) {
                    return []
                }
                const prefilledKeys = new Set(Object.keys(activeSubTemplate?.inputs ?? {}))
                return (selectedTemplate.inputs_schema ?? []).filter(
                    (s) =>
                        s.required &&
                        !prefilledKeys.has(s.key) &&
                        (s.type === 'integration' || s.type === 'integration_field' || s.type === 'string')
                )
            },
        ],

        configuration: [
            (s) => [s.selectedTemplate, s.inputValues],
            (selectedTemplate, inputValues) => ({
                inputs_schema: selectedTemplate?.inputs_schema ?? [],
                inputs: inputValues,
            }),
        ],
    }),

    listeners(({ values, actions }) => ({
        createAlertSuccess: () => {
            actions.resetWizard()
            actions.loadExistingAlerts()
        },

        setAlertCreationView: ({ view }) => {
            if (view === 'wizard') {
                actions.loadExistingAlerts()
            }
        },

        setTriggerKey: () => {
            const destinationKey = values.selectedDestinationKey
            if (destinationKey) {
                const destination = ALL_DESTINATIONS.find((d) => d.key === destinationKey)!
                actions.loadTemplate(destination.templateId)
            }
            actions.setStep('configure')
        },

        submitConfiguration: async () => {
            const destinationKey = values.selectedDestinationKey
            const triggerKey = values.selectedTriggerKey

            if (!destinationKey || !triggerKey) {
                return
            }

            const destination = ALL_DESTINATIONS.find((d) => d.key === destinationKey)!
            const subTemplates = HOG_FUNCTION_SUB_TEMPLATES[triggerKey]
            const subTemplate = subTemplates.find((t) => t.template_id === destination.templateId)

            if (!subTemplate) {
                lemonToast.error('Template not found for this combination')
                return
            }

            const mergedInputs: Record<string, any> = { ...subTemplate.inputs }
            for (const [key, val] of Object.entries(values.inputValues)) {
                mergedInputs[key] = val
            }

            const configuration: Record<string, any> = {
                type: 'internal_destination',
                template_id: destination.templateId,
                filters: subTemplate.filters,
                enabled: true,
                masking: null,
                inputs: mergedInputs,
            }

            try {
                await api.hogFunctions.create(configuration)
                lemonToast.success('Alert created successfully')
                actions.createAlertSuccess()
            } catch (e: any) {
                lemonToast.error(e.detail || 'Failed to create alert')
            }
        },
    })),

    afterMount(({ actions }) => {
        actions.loadExistingAlerts()
    }),
])
