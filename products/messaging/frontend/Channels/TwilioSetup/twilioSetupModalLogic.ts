import { connect, kea, path, props } from 'kea'
import { forms } from 'kea-forms'
import api from 'lib/api'
import { integrationsLogic } from 'lib/integrations/integrationsLogic'
import { lemonToast } from 'lib/lemon-ui/LemonToast'

import { IntegrationType } from '~/types'

import type { twilioSetupModalLogicType } from './twilioSetupModalLogicType'

export interface TwilioSetupModalLogicProps {
    integration?: IntegrationType | null
    onComplete: (integrationId?: number) => void
}

export interface TwilioFormType {
    accountSid: string
    authToken: string
    phoneNumber: string
}

export const twilioSetupModalLogic = kea<twilioSetupModalLogicType>([
    path(['products', 'messaging', 'frontend', 'TwilioSetup', 'twilioSetupModalLogic']),
    props({} as TwilioSetupModalLogicProps),
    connect(() => ({
        values: [integrationsLogic, ['integrations', 'integrationsLoading']],
        actions: [integrationsLogic, ['loadIntegrations']],
    })),
    forms(({ props, actions, values }) => ({
        twilioIntegration: {
            defaults: {
                accountSid: '',
                authToken: '',
                phoneNumber: '',
            },
            errors: ({ accountSid, authToken, phoneNumber }) => ({
                accountSid: accountSid ? undefined : 'Account SID is required',
                authToken: authToken ? undefined : 'Auth Token is required',
                phoneNumber: phoneNumber ? undefined : 'Phone Number is required',
            }),
            submit: async () => {
                try {
                    const integration = await api.integrations.create({
                        kind: 'twilio',
                        config: {
                            account_sid: values.twilioIntegration.accountSid,
                            auth_token: values.twilioIntegration.authToken,
                            phone_number: values.twilioIntegration.phoneNumber,
                        },
                    })
                    actions.loadIntegrations()
                    lemonToast.success('Twilio integration created successfully!')
                    props.onComplete(integration.id)
                } catch (error) {
                    lemonToast.error('Failed to create Twilio integration')
                    throw error
                }
            },
        },
    })),
])
