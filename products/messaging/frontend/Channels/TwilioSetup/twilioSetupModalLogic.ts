import { connect, kea, path, props } from 'kea'
import { forms } from 'kea-forms'
import api from 'lib/api'
import { integrationsLogic } from 'lib/integrations/integrationsLogic'
import { lemonToast } from 'lib/lemon-ui/LemonToast'

import { IntegrationType } from '~/types'

import type { twilioSetupModalLogicType } from './twilioSetupModalLogicType'
import { z } from 'zod'

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
                accountSid: accountSid.trim() ? undefined : 'Account SID is required',
                authToken: authToken.trim() ? undefined : 'Auth Token is required',
                phoneNumber: !phoneNumber
                    ? 'Phone Number is required'
                    : z
                          .string()
                          .regex(/^\+[1-9]\d{1,14}$/, 'Invalid E.164 phone number format.')
                          .safeParse(phoneNumber).error
                    ? 'Invalid E.164 phone number format.'
                    : undefined,
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
                    lemonToast.success('Twilio channel created successfully!')
                    props.onComplete(integration.id)
                } catch (error: any) {
                    lemonToast.error(error.detail || 'Failed to create Twilio channel')
                    throw error
                }
            },
        },
    })),
])
