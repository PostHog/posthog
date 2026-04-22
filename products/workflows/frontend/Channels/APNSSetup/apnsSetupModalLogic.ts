import { connect, kea, path, props } from 'kea'
import { forms } from 'kea-forms'

import api from 'lib/api'
import { integrationsLogic } from 'lib/integrations/integrationsLogic'
import { lemonToast } from 'lib/lemon-ui/LemonToast'

import { IntegrationType } from '~/types'

import type { apnsSetupModalLogicType } from './apnsSetupModalLogicType'

export interface APNSSetupModalLogicProps {
    integration?: IntegrationType | null
    onComplete: (integrationId?: number) => void
    onClose: () => void
}

export interface APNSFormType {
    signingKey: string
    keyId: string
    teamId: string
    bundleId: string
    environment: 'production' | 'sandbox'
}

export const apnsSetupModalLogic = kea<apnsSetupModalLogicType>([
    path(['products', 'workflows', 'frontend', 'APNSSetup', 'apnsSetupModalLogic']),
    props({} as APNSSetupModalLogicProps),
    connect(() => ({
        actions: [integrationsLogic, ['loadIntegrations']],
    })),
    forms(({ props, actions, values }) => ({
        apnsIntegration: {
            defaults: {
                signingKey: '',
                keyId: '',
                teamId: '',
                bundleId: '',
                environment: 'production' as const,
            },
            errors: ({ signingKey, keyId, teamId, bundleId }) => ({
                signingKey: signingKey.trim() ? undefined : 'Signing key is required',
                keyId: keyId.trim() ? undefined : 'Key ID is required',
                teamId: teamId.trim() ? undefined : 'Team ID is required',
                bundleId: bundleId.trim() ? undefined : 'Bundle ID is required',
            }),
            submit: async () => {
                try {
                    const integration = await api.integrations.create({
                        kind: 'apns',
                        config: {
                            signing_key: values.apnsIntegration.signingKey,
                            key_id: values.apnsIntegration.keyId,
                            team_id_apple: values.apnsIntegration.teamId,
                            bundle_id: values.apnsIntegration.bundleId,
                            environment: values.apnsIntegration.environment,
                        },
                    })
                    actions.loadIntegrations()
                    lemonToast.success('APNS channel created successfully!')
                    props.onComplete(integration.id)
                } catch (error: any) {
                    lemonToast.error(error.detail || 'Failed to create APNS channel')
                    throw error
                }
            },
        },
    })),
])
