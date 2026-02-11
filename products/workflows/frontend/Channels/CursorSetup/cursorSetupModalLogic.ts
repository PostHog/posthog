import { connect, kea, path, props } from 'kea'
import { forms } from 'kea-forms'

import api from 'lib/api'
import { integrationsLogic } from 'lib/integrations/integrationsLogic'
import { lemonToast } from 'lib/lemon-ui/LemonToast'

import { IntegrationType } from '~/types'

import type { cursorSetupModalLogicType } from './cursorSetupModalLogicType'

export interface CursorSetupModalLogicProps {
    isOpen?: boolean
    integration?: IntegrationType | null
    onComplete: (integrationId?: number) => void
}

export interface CursorFormType {
    apiKey: string
}

export const cursorSetupModalLogic = kea<cursorSetupModalLogicType>([
    path(['products', 'workflows', 'frontend', 'CursorSetup', 'cursorSetupModalLogic']),
    props({} as CursorSetupModalLogicProps),
    connect(() => ({
        actions: [integrationsLogic, ['loadIntegrations']],
    })),
    forms(({ props, actions, values }) => ({
        cursorIntegration: {
            defaults: {
                apiKey: '',
            },
            errors: ({ apiKey }) => ({
                apiKey: apiKey.trim() ? undefined : 'API key is required',
            }),
            submit: async () => {
                try {
                    const integration = await api.integrations.create({
                        kind: 'cursor',
                        config: {
                            api_key: values.cursorIntegration.apiKey,
                        },
                    })
                    actions.loadIntegrations()
                    lemonToast.success('Cursor integration connected successfully!')
                    props.onComplete(integration.id)
                } catch (error: any) {
                    lemonToast.error(error.detail || 'Failed to connect Cursor integration')
                    throw error
                }
            },
        },
    })),
])
