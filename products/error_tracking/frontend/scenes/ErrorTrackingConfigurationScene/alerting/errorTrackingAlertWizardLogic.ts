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
        setDestination: (destination: WizardDestinationKey) => ({ destination }),
        setTrigger: (trigger: WizardTriggerKey) => ({ trigger }),
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
                setDestination: () => 'trigger' as WizardStep,
                resetWizard: () => 'destination' as WizardStep,
            },
        ],
        selectedDestination: [
            null as WizardDestinationKey | null,
            {
                setDestination: (_, { destination }) => destination,
                resetWizard: () => null,
            },
        ],
        selectedTrigger: [
            null as WizardTriggerKey | null,
            {
                setTrigger: (_, { trigger }) => trigger,
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
                setDestination: () => ({}),
                setTrigger: () => ({}),
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
        usedDestinations: [
            (s) => [s.existingAlerts],
            (existingAlerts): Set<WizardDestinationKey> => {
                const used = new Set<WizardDestinationKey>()
                for (const alert of existingAlerts) {
                    const dest = extractDestinationKeyFromAlert(alert)
                    if (dest) {
                        used.add(dest)
                    }
                }
                return used
            },
        ],

        destinationOptions: [
            (s) => [s.usedDestinations],
            (usedDestinations): WizardDestination[] => {
                const sorted = [...DESTINATIONS_DEFAULT_PRIORITY].sort((a, b) => {
                    const aUsed = usedDestinations.has(a) ? 1 : 0
                    const bUsed = usedDestinations.has(b) ? 1 : 0
                    return bUsed - aUsed
                })
                const top3 = sorted.slice(0, 3)
                return top3.map((key) => ALL_DESTINATIONS.find((d) => d.key === key)!)
            },
        ],

        activeSubTemplate: [
            (s) => [s.selectedDestination, s.selectedTrigger],
            (selectedDestination, selectedTrigger) => {
                if (!selectedDestination || !selectedTrigger) {
                    return null
                }
                const destinationOption = ALL_DESTINATIONS.find((d) => d.key === selectedDestination)
                if (!destinationOption) {
                    return null
                }
                const subTemplates = HOG_FUNCTION_SUB_TEMPLATES[selectedTrigger as HogFunctionSubTemplateIdType]
                return subTemplates?.find((t) => t.template_id === destinationOption.templateId) ?? null
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

        setTrigger: () => {
            const destination = values.selectedDestination
            if (destination) {
                const destinationOptions = ALL_DESTINATIONS.find((d) => d.key === destination)!
                actions.loadTemplate(destinationOptions.templateId)
            }
            actions.setStep('configure')
        },

        submitConfiguration: async () => {
            const dest = values.selectedDestination
            const trigger = values.selectedTrigger

            if (!dest || !trigger) {
                return
            }

            const destOption = ALL_DESTINATIONS.find((d) => d.key === dest)!
            const subTemplates = HOG_FUNCTION_SUB_TEMPLATES[trigger]
            const subTemplate = subTemplates.find((t) => t.template_id === destOption.templateId)

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
                template_id: destOption.templateId,
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
