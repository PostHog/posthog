import { actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { forms } from 'kea-forms'
import { loaders } from 'kea-loaders'

import { lemonToast } from '@posthog/lemon-ui'

import api from 'lib/api'
import { integrationsLogic } from 'lib/integrations/integrationsLogic'
import {
    HOG_FUNCTION_SUB_TEMPLATES,
    HOG_FUNCTION_SUB_TEMPLATE_COMMON_PROPERTIES,
} from 'scenes/hog-functions/sub-templates/sub-templates'

import { HogFunctionType, IntegrationType } from '~/types'

import type { errorTrackingAlertWizardLogicType } from './errorTrackingAlertWizardLogicType'

export type WizardDestination = 'slack' | 'discord' | 'github' | 'microsoft-teams' | 'linear'
export type WizardTrigger = 'error-tracking-issue-created' | 'error-tracking-issue-reopened'
export type WizardStep = 'destination' | 'trigger' | 'configure'

export interface DestinationOption {
    key: WizardDestination
    name: string
    description: string
    icon: string
    templatePrefix: string
}

const ALL_DESTINATIONS: DestinationOption[] = [
    {
        key: 'slack',
        name: 'Slack',
        description: 'Send a message to a channel',
        icon: '/static/services/slack.png',
        templatePrefix: 'template-slack',
    },
    {
        key: 'discord',
        name: 'Discord',
        description: 'Post a notification via webhook',
        icon: '/static/services/discord.png',
        templatePrefix: 'template-discord',
    },
    {
        key: 'github',
        name: 'GitHub',
        description: 'Create an issue in a repository',
        icon: '/static/services/github.png',
        templatePrefix: 'template-github',
    },
    {
        key: 'microsoft-teams',
        name: 'Microsoft Teams',
        description: 'Send a message to a channel',
        icon: '/static/services/microsoft-teams.png',
        templatePrefix: 'template-microsoft-teams',
    },
    {
        key: 'linear',
        name: 'Linear',
        description: 'Create an issue in a project',
        icon: '/static/services/linear.png',
        templatePrefix: 'template-linear',
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
        if (templateId.startsWith(dest.templatePrefix)) {
            return dest.key
        }
    }
    return null
}

export const errorTrackingAlertWizardLogic = kea<errorTrackingAlertWizardLogicType>([
    path(['products', 'error_tracking', 'frontend', 'alerting', 'errorTrackingAlertWizardLogic']),

    connect(() => ({
        values: [integrationsLogic, ['slackIntegrations', 'slackAvailable', 'integrations']],
    })),

    actions({
        setStep: (step: WizardStep) => ({ step }),
        setDestination: (destination: WizardDestination) => ({ destination }),
        setTrigger: (trigger: WizardTrigger) => ({ trigger }),
        resetWizard: true,
        createAlertSuccess: true,
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

        githubIntegrations: [
            (s) => [s.integrations],
            (integrations): IntegrationType[] => {
                return integrations?.filter((x) => x.kind === 'github') || []
            },
        ],

        linearIntegrations: [
            (s) => [s.integrations],
            (integrations): IntegrationType[] => {
                return integrations?.filter((x) => x.kind === 'linear') || []
            },
        ],
    }),

    forms(({ values, actions }) => ({
        configForm: {
            defaults: {
                discordWebhookUrl: '' as string,
                microsoftTeamsWebhookUrl: '' as string,
                slackWorkspaceId: undefined as number | undefined,
                slackChannelId: undefined as string | undefined,
                githubIntegrationId: undefined as number | undefined,
                githubRepository: '' as string,
                linearIntegrationId: undefined as number | undefined,
                linearTeamId: '' as string,
            },

            errors: (values_form) => {
                const dest = values.selectedDestination
                return {
                    discordWebhookUrl:
                        dest === 'discord' && !values_form.discordWebhookUrl
                            ? 'Please enter a Discord webhook URL'
                            : undefined,
                    microsoftTeamsWebhookUrl:
                        dest === 'microsoft-teams' && !values_form.microsoftTeamsWebhookUrl
                            ? 'Please enter a Microsoft Teams webhook URL'
                            : undefined,
                    slackChannelId:
                        dest === 'slack' && !values_form.slackChannelId ? 'Please choose a Slack channel' : undefined,
                    githubRepository:
                        dest === 'github' && !values_form.githubRepository ? 'Please select a repository' : undefined,
                    linearTeamId: dest === 'linear' && !values_form.linearTeamId ? 'Please select a team' : undefined,
                }
            },

            submit: async (formValues) => {
                const dest = values.selectedDestination
                const trigger = values.selectedTrigger

                if (!dest || !trigger) {
                    return
                }

                const destOption = ALL_DESTINATIONS.find((d) => d.key === dest)!
                const subTemplates = HOG_FUNCTION_SUB_TEMPLATES[trigger]
                const subTemplate = subTemplates.find((t) => t.template_id === destOption.templatePrefix)

                if (!subTemplate) {
                    lemonToast.error('Template not found for this combination')
                    return
                }

                const configuration: Record<string, any> = {
                    type: 'internal_destination',
                    template_id: destOption.templatePrefix,
                    filters: subTemplate.filters,
                    enabled: true,
                    masking: null,
                    inputs: { ...subTemplate.inputs },
                }

                if (dest === 'slack') {
                    configuration.inputs = {
                        ...configuration.inputs,
                        slack_workspace: { value: formValues.slackWorkspaceId },
                        channel: { value: formValues.slackChannelId },
                    }
                } else if (dest === 'discord') {
                    configuration.inputs = {
                        ...configuration.inputs,
                        webhookUrl: { value: formValues.discordWebhookUrl },
                    }
                } else if (dest === 'microsoft-teams') {
                    configuration.inputs = {
                        ...configuration.inputs,
                        webhookUrl: { value: formValues.microsoftTeamsWebhookUrl },
                    }
                } else if (dest === 'github') {
                    configuration.inputs = {
                        ...configuration.inputs,
                        github_integration: { value: formValues.githubIntegrationId },
                        repositories: { value: formValues.githubRepository ? [formValues.githubRepository] : [] },
                    }
                } else if (dest === 'linear') {
                    configuration.inputs = {
                        ...configuration.inputs,
                        linear_integration: { value: formValues.linearIntegrationId },
                        teamIds: { value: formValues.linearTeamId ? [formValues.linearTeamId] : [] },
                    }
                }

                await api.hogFunctions.create(configuration)
                lemonToast.success('Alert created successfully')
                actions.createAlertSuccess()
            },
        },
    })),

    listeners(({ actions }) => ({
        setTrigger: () => {
            actions.setStep('configure')
        },
    })),

    afterMount(({ actions }) => {
        actions.loadExistingAlerts()
    }),
])
