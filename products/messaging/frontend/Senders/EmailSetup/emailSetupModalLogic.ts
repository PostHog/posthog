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
    status: string
    recordValue: string
    recordType: string
    recordHostname: string
}

export interface DomainFormType {
    domain: string
}

export const emailSetupModalLogic = kea<emailSetupModalLogicType>([
    path(['products', 'messaging', 'frontend', 'EmailSetup', 'emailSetupModalLogic']),
    props({} as EmailSetupModalLogicProps),
    key(({ integration }) => (integration ? `messaging-sender-setup-${integration.id}` : 'messaging-sender-setup-new')),
    connect(() => ({
        values: [integrationsLogic, ['integrations']],
        actions: [integrationsLogic, ['loadIntegrations']],
    })),
    forms(({ actions }) => ({
        emailSender: {
            defaults: {
                domain: '',
            },
            errors: ({ domain }) => {
                let domainError = undefined
                if (!domain) {
                    domainError = 'Domain is required'
                }
                const domainRegex = /^([a-z0-9]+(-[a-z0-9]+)*\.)+[a-z]{2,}$/i
                if (!domainRegex.test(domain)) {
                    domainError = 'Invalid domain format'
                }
                return {
                    domain: domainError,
                }
            },
            submit: async () => {
                actions.submitDomain()
            },
        },
    })),
    loaders(({ actions, values }) => ({
        integration: {
            submitDomain: async () => {
                const integration = await api.integrations.create({
                    kind: 'email',
                    config: {
                        domain: values.emailSender.domain,
                    },
                })
                actions.loadIntegrations()
                return integration
            },
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
        setIntegrationSuccess: () => {
            // After setting a pre-existing integration, verify the domain
            actions.verifyDomain()
        },
        submitDomainSuccess: () => {
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
        }
    }),
])
