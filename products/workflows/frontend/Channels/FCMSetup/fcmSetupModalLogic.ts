import { connect, kea, path, props } from 'kea'
import { forms } from 'kea-forms'

import api from 'lib/api'
import { integrationsLogic } from 'lib/integrations/integrationsLogic'
import { lemonToast } from 'lib/lemon-ui/LemonToast'

import { IntegrationType } from '~/types'

import type { fcmSetupModalLogicType } from './fcmSetupModalLogicType'

export interface FCMSetupModalLogicProps {
    integration?: IntegrationType | null
    onComplete: (integrationId?: number) => void
    onClose: () => void
}

export interface FCMFormType {
    serviceAccountKey: string
}

export const fcmSetupModalLogic = kea<fcmSetupModalLogicType>([
    path(['products', 'workflows', 'frontend', 'FCMSetup', 'fcmSetupModalLogic']),
    props({} as FCMSetupModalLogicProps),
    connect(() => ({
        actions: [integrationsLogic, ['loadIntegrations']],
    })),
    forms(({ props, actions, values }) => ({
        fcmIntegration: {
            defaults: {
                serviceAccountKey: '',
            },
            errors: ({ serviceAccountKey }) => ({
                serviceAccountKey: serviceAccountKey.trim() ? undefined : 'Service account key is required',
            }),
            submit: async () => {
                let keyInfo: Record<string, unknown>
                try {
                    keyInfo = JSON.parse(values.fcmIntegration.serviceAccountKey)
                } catch {
                    lemonToast.error('Invalid JSON in service account key')
                    throw new Error('Invalid JSON')
                }

                try {
                    const integration = await api.integrations.create({
                        kind: 'firebase',
                        config: {
                            key_info: keyInfo,
                        },
                    })
                    actions.loadIntegrations()
                    lemonToast.success('Firebase Cloud Messaging channel created successfully!')
                    props.onComplete(integration.id)
                } catch (error: any) {
                    lemonToast.error(error.detail || 'Failed to create Firebase channel')
                    throw error
                }
            },
        },
    })),
])
