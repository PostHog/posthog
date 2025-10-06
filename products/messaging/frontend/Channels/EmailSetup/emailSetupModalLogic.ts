import { afterMount, connect, kea, key, listeners, path, props, selectors } from 'kea'
import { forms } from 'kea-forms'
import { loaders } from 'kea-loaders'

import api from 'lib/api'
import { integrationsLogic } from 'lib/integrations/integrationsLogic'
import { lemonToast } from 'lib/lemon-ui/LemonToast'

import { IntegrationType } from '~/types'

import type { emailSetupModalLogicType } from './emailSetupModalLogicType'

export interface EmailSetupModalLogicProps {
    integration?: IntegrationType | null
    onComplete: (integrationId?: number) => void
}

export interface DnsRecord {
    type: string
    status: 'success' | 'pending'
    recordValue: string
    recordType: string
    recordHostname: string
}

export interface EmailSenderFormType {
    email: string
    name: string
    provider: 'ses' | 'mailjet' | 'maildev'
}

const EMAIL_REGEX = /^[^\s@]+@[^\s@]+\.[^\s@]+$/i

export const emailSetupModalLogic = kea<emailSetupModalLogicType>([
    path(['products', 'messaging', 'frontend', 'EmailSetup', 'emailSetupModalLogic']),
    props({} as EmailSetupModalLogicProps),
    key(({ integration }) => (integration ? `messaging-sender-setup-${integration.id}` : 'messaging-sender-setup-new')),
    connect(() => ({
        values: [integrationsLogic, ['integrations', 'integrationsLoading']],
        actions: [integrationsLogic, ['loadIntegrations']],
    })),
    forms(({ actions }) => ({
        emailSender: {
            defaults: {
                provider: 'mailjet',
                email: '',
                name: '',
            } as EmailSenderFormType,
            errors: ({ email, name, provider }) => {
                let emailError = undefined
                if (!email) {
                    emailError = 'Email is required'
                }
                if (!EMAIL_REGEX.test(email)) {
                    emailError = 'Invalid email format'
                }
                return {
                    email: emailError,
                    name: !name ? 'Name is required' : undefined,
                    provider: !provider ? 'Provider is required' : undefined,
                }
            },
            submit: async (config) => {
                try {
                    const integration = await api.integrations.create({
                        kind: 'email',
                        config: config,
                    })
                    actions.loadIntegrations()
                    actions.setIntegration(integration)
                    actions.verifyDomain()
                    return config
                } catch (error) {
                    console.error(error)
                    actions.setEmailSenderManualErrors({
                        email: JSON.stringify(error),
                    })
                    throw error
                }
            },
        },
    })),
    loaders(({ values }) => ({
        integration: {
            setIntegration: (integration?: IntegrationType) => integration,
        },
        verification: {
            verifyDomain: async () => {
                return api.integrations.verifyEmail(values.integration.id)
            },
        },
    })),
    selectors({
        dnsRecords: [
            (s) => [s.verification],
            (verification: { status: string } | null) => verification?.status || null,
        ],
    }),
    listeners(({ props, values, actions }) => ({
        submitEmailSenderSuccess: () => {
            // After creating the integration, verify the domain
            actions.verifyDomain()
        },
        verifyDomainSuccess: ({ verification }) => {
            if (verification.status === 'success') {
                lemonToast.success('Domain verified successfully!')
                actions.loadIntegrations()
                props.onComplete(values.integration.id)
            }
        },
    })),
    afterMount(({ props, actions }) => {
        if (props.integration) {
            actions.setIntegration(props.integration)
            actions.verifyDomain()
        }
    }),
])
