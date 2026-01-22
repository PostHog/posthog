import { actions, afterMount, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
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
    mail_from_subdomain?: string
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

const getEmailSenderFromIntegration = (integration: IntegrationType): EmailSenderFormType => {
    return {
        email: integration.config.email,
        name: integration.config.name,
        provider: integration.config.provider,
        mail_from_subdomain: integration.config.mail_from_subdomain,
    }
}

export const emailSetupModalLogic = kea<emailSetupModalLogicType>([
    path(['products', 'workflows', 'frontend', 'EmailSetup', 'emailSetupModalLogic']),
    props({} as EmailSetupModalLogicProps),
    key(({ integration }) => (integration ? `workflows-sender-setup-${integration.id}` : 'workflows-sender-setup-new')),
    connect(() => ({
        values: [integrationsLogic, ['integrations', 'integrationsLoading']],
        actions: [integrationsLogic, ['loadIntegrations']],
    })),
    actions({
        setSavedIntegration: (integration: IntegrationType | null) => ({ integration }),
        verifyDomain: true,
    }),
    reducers({
        savedIntegration: [
            null as IntegrationType | null,
            {
                setSavedIntegration: (_, { integration }) => integration || null,
            },
        ],
    }),
    forms(({ actions, values }) => ({
        emailSender: {
            defaults: {
                provider: 'ses',
                email: '',
                name: '',
                mail_from_subdomain: 'feedback',
            } as EmailSenderFormType,
            errors: ({ email, name, provider, mail_from_subdomain }) => {
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
                    mail_from_subdomain:
                        values.savedIntegration === null && !mail_from_subdomain
                            ? 'MAIL FROM subdomain is required for new senders'
                            : undefined,
                }
            },
            submit: async (config) => {
                try {
                    let integration: IntegrationType
                    if (values.savedIntegration) {
                        integration = await api.integrations.updateEmailConfig(values.savedIntegration.id, {
                            config,
                        })
                    } else {
                        integration = await api.integrations.create({
                            kind: 'email',
                            config,
                        })
                    }
                    actions.loadIntegrations()
                    actions.setSavedIntegration(integration)
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
        verification: {
            verifyDomain: async () => {
                if (values.savedIntegration) {
                    return api.integrations.verifyEmail(values.savedIntegration.id)
                }
            },
        },
    })),
    selectors({
        dnsRecords: [
            (s) => [s.verification, s.savedIntegration],
            (
                verification: { dnsRecords?: ApiDnsRecord[] } | null,
                savedIntegration: IntegrationType | undefined
            ): DnsRecord[] => {
                if (!verification?.dnsRecords || !savedIntegration) {
                    return []
                }
                const rootDomain = savedIntegration?.config?.domain || ''
                return verification.dnsRecords.map((record) => ({
                    ...record,
                    parsedHostname: parseHostname(record.recordHostname, rootDomain),
                }))
            },
        ],
        domain: [
            (s) => [s.emailSender],
            (emailSender: EmailSenderFormType): string => {
                return emailSender.email.includes('@') ? emailSender.email.split('@')[1] : ''
            },
        ],
        isDomainVerified: [
            (s) => [s.verification],
            (verification: { status: string } | null): boolean => {
                return verification?.status === 'success'
            },
        ],
    }),
    listeners(({ actions }) => ({
        verifyDomainSuccess: ({ verification }) => {
            if (verification?.status === 'success') {
                actions.loadIntegrations()
            }
        },
    })),
    afterMount(({ props, actions }) => {
        if (props.integration) {
            actions.setSavedIntegration(props.integration)
            actions.setEmailSenderValues(getEmailSenderFromIntegration(props.integration))
            actions.verifyDomain()
        }
    }),
])
