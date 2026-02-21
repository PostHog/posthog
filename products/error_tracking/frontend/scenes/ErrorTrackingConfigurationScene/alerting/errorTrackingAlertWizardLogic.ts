import { actions, afterMount, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { actionToUrl, router, urlToAction } from 'kea-router'

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

const ALL_TRIGGERS: WizardTrigger[] = [
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

function hasSubTemplateForDestination(triggerKey: WizardTriggerKey, destination: WizardDestination): boolean {
    const subTemplates = HOG_FUNCTION_SUB_TEMPLATES[triggerKey as HogFunctionSubTemplateIdType]
    return subTemplates?.some((t) => t.template_id === destination.templateId) ?? false
}

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
        restoreWizardState: (state: {
            step: WizardStep
            destinationKey: WizardDestinationKey | null
            triggerKey: WizardTriggerKey | null
        }) => ({ state }),
        resetWizard: true,
        createAlertSuccess: true,
        submitConfiguration: true,
        testConfiguration: true,
        testConfigurationComplete: true,
    }),

    reducers({
        alertCreationView: [
            'none' as AlertCreationView,
            {
                setAlertCreationView: (_, { view }) => view,
                restoreWizardState: () => 'wizard' as AlertCreationView,
                createAlertSuccess: () => 'none' as AlertCreationView,
            },
        ],
        currentStep: [
            'destination' as WizardStep,
            {
                setStep: (_, { step }) => step,
                setDestinationKey: () => 'trigger' as WizardStep,
                restoreWizardState: (_, { state }) => state.step,
                resetWizard: () => 'destination' as WizardStep,
            },
        ],
        selectedDestinationKey: [
            null as WizardDestinationKey | null,
            {
                setDestinationKey: (_, { destinationKey }) => destinationKey,
                restoreWizardState: (_, { state }) => state.destinationKey,
                resetWizard: () => null,
            },
        ],
        selectedTriggerKey: [
            null as WizardTriggerKey | null,
            {
                setTriggerKey: (_, { triggerKey }) => triggerKey,
                restoreWizardState: (_, { state }) => state.triggerKey,
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
        testing: [
            false,
            {
                testConfiguration: () => true,
                testConfigurationComplete: () => false,
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

        availableTriggers: [
            (s) => [s.selectedDestinationKey],
            (selectedDestinationKey): WizardTrigger[] => {
                if (!selectedDestinationKey) {
                    return ALL_TRIGGERS
                }
                const destination = ALL_DESTINATIONS.find((d) => d.key === selectedDestinationKey)
                if (!destination) {
                    return ALL_TRIGGERS
                }
                return ALL_TRIGGERS.filter((trigger) => hasSubTemplateForDestination(trigger.key, destination))
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

        restoreWizardState: ({ state }) => {
            if (state.destinationKey && state.triggerKey) {
                const destination = ALL_DESTINATIONS.find((d) => d.key === state.destinationKey)
                if (destination) {
                    actions.loadTemplate(destination.templateId)
                }
            }
            actions.loadExistingAlerts()
        },

        setTriggerKey: () => {
            const destinationKey = values.selectedDestinationKey
            if (destinationKey) {
                const destination = ALL_DESTINATIONS.find((d) => d.key === destinationKey)!
                actions.loadTemplate(destination.templateId)
            }
            actions.setStep('configure')
        },

        testConfiguration: async (_, breakpoint) => {
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

            const selectedTemplate = values.selectedTemplate
            if (!selectedTemplate) {
                lemonToast.error('Template not loaded yet')
                actions.testConfigurationComplete()
                return
            }

            const configuration: Record<string, any> = {
                type: 'internal_destination',
                template_id: destination.templateId,
                filters: subTemplate.filters,
                enabled: true,
                masking: null,
                inputs: mergedInputs,
                inputs_schema: selectedTemplate.inputs_schema,
                hog: selectedTemplate.code,
            }

            const globals = {
                event: {
                    uuid: 'test-event-uuid',
                    distinct_id: 'test-distinct-id',
                    timestamp: new Date().toISOString(),
                    event: subTemplate.filters?.events?.[0]?.id || triggerKey,
                    properties: {
                        name: 'Test issue',
                        description: 'This is a test alert from PostHog',
                    },
                },
                project: {
                    id: 0,
                    name: 'Test project',
                    url: window.location.origin,
                },
                source: {
                    name: 'Error tracking alert wizard',
                    url: window.location.href,
                },
            }

            try {
                await api.hogFunctions.createTestInvocation('new', {
                    configuration,
                    globals,
                    mock_async_functions: false,
                })
                breakpoint()
                lemonToast.success('Test invocation sent')
            } catch (e: any) {
                breakpoint()
                lemonToast.error(e.detail || 'Test invocation failed')
            }

            actions.testConfigurationComplete()
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

    actionToUrl(({ values }) => {
        const buildURL = (): [string, Record<string, any>, Record<string, any>] => {
            const { currentLocation } = router.values
            const searchParams = { ...currentLocation.searchParams }

            if (values.alertCreationView === 'wizard') {
                searchParams.wizard_step = values.currentStep
                if (values.selectedDestinationKey) {
                    searchParams.wizard_dest = values.selectedDestinationKey
                } else {
                    delete searchParams.wizard_dest
                }
                if (values.selectedTriggerKey) {
                    searchParams.wizard_trigger = values.selectedTriggerKey
                } else {
                    delete searchParams.wizard_trigger
                }
            } else {
                delete searchParams.wizard_step
                delete searchParams.wizard_dest
                delete searchParams.wizard_trigger
            }

            return [currentLocation.pathname, searchParams, currentLocation.hashParams]
        }

        return {
            setAlertCreationView: buildURL,
            setStep: buildURL,
            setDestinationKey: buildURL,
            setTriggerKey: buildURL,
            resetWizard: buildURL,
            createAlertSuccess: buildURL,
        }
    }),

    urlToAction(({ actions, values }) => ({
        '**/error_tracking/configuration': (_, searchParams) => {
            const wizardStep = searchParams.wizard_step as WizardStep | undefined
            const wizardDest = searchParams.wizard_dest as WizardDestinationKey | undefined
            const wizardTrigger = searchParams.wizard_trigger as WizardTriggerKey | undefined

            if (wizardStep && values.alertCreationView !== 'wizard') {
                actions.restoreWizardState({
                    step: wizardStep,
                    destinationKey: wizardDest ?? null,
                    triggerKey: wizardTrigger ?? null,
                })
            }
        },
    })),

    afterMount(({ actions }) => {
        actions.loadExistingAlerts()
    }),
])
