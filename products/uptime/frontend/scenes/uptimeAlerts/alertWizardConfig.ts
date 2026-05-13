import { WizardDestination, WizardTrigger } from 'scenes/hog-functions/AlertWizard/alertWizardLogic'

import { HogFunctionSubTemplateIdType } from '~/types'

export const UPTIME_SUB_TEMPLATE_IDS: HogFunctionSubTemplateIdType[] = ['uptime-monitor-status-changed']

export const UPTIME_TRIGGERS: WizardTrigger[] = [
    {
        key: 'uptime-monitor-status-changed',
        name: 'Monitor status changed',
        description: 'Get notified when a monitor goes down or recovers',
    },
]

export const UPTIME_DESTINATIONS: WizardDestination[] = [
    {
        key: 'discord',
        name: 'Discord',
        description: 'Post a notification via webhook',
        icon: '/static/services/discord.png',
        templateId: 'native-discord-uptime',
    },
]
