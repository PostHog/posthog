import { afterMount, connect, kea, key, listeners, path, props, selectors } from 'kea'
import { forms } from 'kea-forms'
import { loaders } from 'kea-loaders'

import api, { ApiError } from 'lib/api'
import { integrationsLogic } from 'lib/integrations/integrationsLogic'
import { lemonToast } from 'lib/lemon-ui/LemonToast'

import { IntegrationType } from '~/types'

import type { emailSetupModalLogicType } from './emailSetupModalLogicType'

export interface EmailSetupModalLogicProps {
    integration?: IntegrationType | null
    onComplete: (integrationId?: number) => void
}

export interface ApiDnsRecord {
    type: string
    status: 'success' | 'pending'
    recordValue: string
    recordType: string
    recordHostname: string
}

export interface DnsRecord extends ApiDnsRecord {
    parsedHostname: { subdomain: string; rootDomain: string }
}

export interface EmailSenderFormType {
    email: string
    name: string
    provider: 'ses' | 'maildev'
}

const EMAIL_REGEX = /^[^\s@]+@[^\s@]+\.[^\s@]+$/i

export const parseHostname = (hostname: string, rootDomain: string): { subdomain: string; rootDomain: string } => {
    if (hostname === '@') {
        return { subdomain: '@', rootDomain: '' }
    }

    if (hostname.endsWith(`.${rootDomain}`)) {
        const subdomain = hostname.slice(0, -rootDomain.length - 1)
        return { subdomain, rootDomain: `.${rootDomain}` }
    }

    // Fallback: return as subdomain if we can't parse it
    return { subdomain: hostname, rootDomain: '' }
}

export const emailSetupModalLogic = kea<emailSetupModalLogicType>([
    path(['products', 'workflows', 'frontend', 'EmailSetup', 'emailSetupModalLogic']),
    props({} as EmailSetupModalLogicProps),
    key(({ integration }) => (integration ? `workflows-sender-setup-${integration.id}` : 'workflows-sender-setup-new')),
    connect(() => ({
        values: [integrationsLogic, ['integrations', 'integrationsLoading']],
        actions: [integrationsLogic, ['loadIntegrations']],
    })),
    forms(({ actions }) => ({
        emailSender: {
            defaults: {
                provider: 'ses',
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
                    if (error instanceof ApiError || (error && typeof error === 'object' && 'detail' in error)) {
                        lemonToast.error(`Failed to create email sender: ${error.detail || 'Please try again.'}`)
                    }
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
            (s) => [s.verification, s.integration],
            (
                verification: { dnsRecords?: ApiDnsRecord[] } | null,
                integration: IntegrationType | undefined
            ): DnsRecord[] => {
                if (!verification?.dnsRecords || !integration) {
                    return []
                }
                const rootDomain = integration?.config?.domain || ''
                return verification.dnsRecords.map((record) => ({
                    ...record,
                    parsedHostname: parseHostname(record.recordHostname, rootDomain),
                }))
            },
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
