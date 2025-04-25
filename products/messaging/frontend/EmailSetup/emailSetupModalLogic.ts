import { actions, kea, key, listeners, path, props, selectors } from 'kea'
import { forms } from 'kea-forms'
import { loaders } from 'kea-loaders'
import { lemonToast } from 'lib/lemon-ui/LemonToast'

import type { emailSetupModalLogicType } from './emailSetupModalLogicType'

export interface EmailSetupModalLogicProps {
    onComplete: (domain: string) => void
}

export interface DnsRecord {
    type: string
    name: string
    value: string
}

export interface DomainFormType {
    domain: string
}

// Using 'any' temporarily until typegen runs
export const emailSetupModalLogic = kea<emailSetupModalLogicType>([
    path(['products', 'messaging', 'frontend', 'EmailSetup', 'emailSetupModalLogic']),
    props({} as EmailSetupModalLogicProps),
    key(() => 'global'),
    actions({
        submitDomain: (domain: string) => ({ domain }),
        verifyDomain: true,
        resetState: true,
        setDomain: (domain: string) => ({ domain }),
    }),
    forms(({ actions }) => ({
        emailIntegration: {
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
            submit: async ({ domain }) => {
                actions.submitDomain(domain)
            },
        },
    })),
    loaders(({ values }) => ({
        setupResponse: [
            null as null | { records: DnsRecord[] },
            {
                submitDomain: async ({ domain }) => {
                    try {
                        const response = await fetch(`/api/projects/@current/message_setup/email`, {
                            method: 'POST',
                            headers: {
                                'Content-Type': 'application/json',
                            },
                            body: JSON.stringify({ domain }),
                        })

                        if (!response.ok) {
                            throw new Error('Failed to setup domain')
                        }

                        return await response.json()
                    } catch (error) {
                        lemonToast.error('Failed to create email sender domain')
                        throw error
                    }
                },
            },
        ],
        verificationResponse: [
            null as null | { verified: boolean },
            {
                verifyDomain: async () => {
                    const domain = values.emailIntegration.domain
                    try {
                        const response = await fetch(`/api/projects/@current/message_setup/email/verify`, {
                            method: 'POST',
                            headers: {
                                'Content-Type': 'application/json',
                            },
                            body: JSON.stringify({ domain }),
                        })

                        if (!response.ok) {
                            throw new Error('Failed to verify domain')
                        }

                        return await response.json()
                    } catch (error) {
                        lemonToast.error('Failed to verify domain')
                        throw error
                    }
                },
            },
        ],
    })),
    selectors({
        dnsRecords: [
            (s) => [s.setupResponse],
            (setupResponse: { records: DnsRecord[] } | null) => setupResponse?.records || [],
        ],
    }),
    listeners(({ props, values }) => ({
        verifyDomainSuccess: ({ verificationResponse }) => {
            if (verificationResponse?.verified) {
                lemonToast.success('Domain verified successfully!')
                props.onComplete(values.emailIntegration.domain)
            } else {
                lemonToast.warning('Domain verification failed. Please check your DNS records and try again.')
            }
        },
    })),
])
