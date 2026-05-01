import { WizardDestination, WizardTrigger } from 'scenes/hog-functions/AlertWizard/alertWizardLogic'

import { HogFunctionSubTemplateIdType } from '~/types'

export const ERROR_TRACKING_SUB_TEMPLATE_IDS: HogFunctionSubTemplateIdType[] = [
    'error-tracking-issue-created',
    'error-tracking-issue-reopened',
    'error-tracking-issue-spiking',
]

export const ERROR_TRACKING_TRIGGERS: WizardTrigger[] = [
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
    {
        key: 'error-tracking-issue-spiking',
        name: 'Issue spiking',
        description: 'Get notified when an issue starts occurring more frequently than usual',
    },
]

export const ERROR_TRACKING_DESTINATIONS: WizardDestination[] = [
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
        key: 'gitlab',
        name: 'GitLab',
        description: 'Create an issue in a project',
        icon: '/static/services/gitlab.png',
        templateId: 'template-gitlab',
    },
    {
        key: 'microsoft-teams',
        name: 'Teams',
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
