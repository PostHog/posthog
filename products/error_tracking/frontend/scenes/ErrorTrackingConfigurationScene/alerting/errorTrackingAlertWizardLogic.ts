import { actions, afterMount, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import { lemonToast } from '@posthog/lemon-ui'

import api from 'lib/api'
import {
    HOG_FUNCTION_SUB_TEMPLATES,
    HOG_FUNCTION_SUB_TEMPLATE_COMMON_PROPERTIES,
} from 'scenes/hog-functions/sub-templates/sub-templates'

import { CyclotronJobInputType, HogFunctionTemplateType, HogFunctionType } from '~/types'

import type { errorTrackingAlertWizardLogicType } from './errorTrackingAlertWizardLogicType'

export type WizardDestination = 'slack' | 'discord' | 'github' | 'microsoft-teams' | 'linear'
export type WizardTrigger = 'error-tracking-issue-created' | 'error-tracking-issue-reopened'
export type WizardStep = 'destination' | 'trigger' | 'configure'

export interface DestinationOption {
    key: WizardDestination
    name: string
    description: string
    icon: string
    templateId: string
}

const ALL_DESTINATIONS: DestinationOption[] = [
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

const DEFAULT_PRIORITY: WizardDestination[] = ['slack', 'discord', 'github', 'microsoft-teams', 'linear']

export interface TriggerOption {
    key: WizardTrigger
    name: string
    description: string
}

export const TRIGGER_OPTIONS: TriggerOption[] = [
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

function extractDestinationFromTemplateId(templateId: string | undefined): WizardDestination | null {
    if (!templateId) {
        return null
    }
    for (const dest of ALL_DESTINATIONS) {
        if (templateId.startsWith(dest.templateId)) {
            return dest.key
        }
    }
    return null
}

export const errorTrackingAlertWizardLogic = kea<errorTrackingAlertWizardLogicType>([
    path(['products', 'error_tracking', 'frontend', 'alerting', 'errorTrackingAlertWizardLogic']),

    actions({
        setStep: (step: WizardStep) => ({ step }),
        setDestination: (destination: WizardDestination) => ({ destination }),
        setTrigger: (trigger: WizardTrigger) => ({ trigger }),
        setInputValue: (key: string, value: CyclotronJobInputType) => ({ key, value }),
        resetWizard: true,
        createAlertSuccess: true,
        submitConfiguration: true,
    }),

    reducers({
        currentStep: [
            'destination' as WizardStep,
            {
                setStep: (_, { step }) => step,
                setDestination: () => 'trigger' as WizardStep,
                resetWizard: () => 'destination' as WizardStep,
            },
        ],
        selectedDestination: [
            null as WizardDestination | null,
            {
                setDestination: (_, { destination }) => destination,
                resetWizard: () => null,
            },
        ],
        selectedTrigger: [
            null as WizardTrigger | null,
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
        destinationOptions: [
            (s) => [s.existingAlerts],
            (existingAlerts): DestinationOption[] => {
                const counts: Record<string, number> = {}
                for (const alert of existingAlerts) {
                    const dest = extractDestinationFromTemplateId(alert.template_id)
                    if (dest) {
                        counts[dest] = (counts[dest] || 0) + 1
                    }
                }

                const sorted = [...DEFAULT_PRIORITY].sort((a, b) => (counts[b] || 0) - (counts[a] || 0))
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
                const destOption = ALL_DESTINATIONS.find((d) => d.key === selectedDestination)
                if (!destOption) {
                    return null
                }
                const subTemplates = HOG_FUNCTION_SUB_TEMPLATES[selectedTrigger]
                return subTemplates?.find((t) => t.template_id === destOption.templateId) ?? null
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
        setTrigger: () => {
            const dest = values.selectedDestination
            if (dest) {
                const destOption = ALL_DESTINATIONS.find((d) => d.key === dest)!
                actions.loadTemplate(destOption.templateId)
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
