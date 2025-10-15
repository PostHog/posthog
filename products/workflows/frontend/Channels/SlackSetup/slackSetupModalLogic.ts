import { connect, kea, path, props } from 'kea'
import { forms } from 'kea-forms'

import api from 'lib/api'
import { integrationsLogic } from 'lib/integrations/integrationsLogic'
import { lemonToast } from 'lib/lemon-ui/LemonToast'
import { userLogic } from 'scenes/userLogic'

import { IntegrationType } from '~/types'

import type { slackSetupModalLogicType } from './slackSetupModalLogicType'

export interface SlackSetupModalLogicProps {
    integration?: IntegrationType | null
    onComplete: (integrationId?: number) => void
}

export interface SlackFormType {
    botToken: string
    channelId: string
}

export const slackSetupModalLogic = kea<slackSetupModalLogicType>([
    path(['products', 'workflows', 'frontend', 'SlackSetup', 'slackSetupModalLogic']),
    props({} as SlackSetupModalLogicProps),
    connect(() => ({
        values: [integrationsLogic, ['integrations', 'integrationsLoading', 'slackAvailable'], userLogic, ['user']],
        actions: [integrationsLogic, ['loadIntegrations']],
    })),
    forms(({ props, actions, values }) => ({
        slackIntegration: {
            defaults: {
                botToken: '',
                channelId: '',
            },
            errors: ({ botToken, channelId }) => ({
                botToken: botToken ? undefined : 'Bot Token is required',
                channelId: channelId ? undefined : 'Channel ID is required',
            }),
            submit: async () => {
                try {
                    const integration = await api.integrations.create({
                        kind: 'slack',
                        config: {
                            bot_token: values.slackIntegration.botToken,
                            channel_id: values.slackIntegration.channelId,
                        },
                    })
                    actions.loadIntegrations()
                    lemonToast.success('Slack integration created successfully!')
                    props.onComplete(integration.id)
                } catch (error) {
                    lemonToast.error('Failed to create Slack integration')
                    throw error
                }
            },
        },
    })),
])
