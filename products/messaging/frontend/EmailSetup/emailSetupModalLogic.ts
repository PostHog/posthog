import { kea, key, listeners, path, props, selectors } from 'kea'
import { forms } from 'kea-forms'
import { loaders } from 'kea-loaders'
import api from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast'

import type { emailSetupModalLogicType } from './emailSetupModalLogicType'

export interface EmailSetupModalLogicProps {
    onComplete: (domain: string) => void
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

// Using 'any' temporarily until typegen runs
export const emailSetupModalLogic = kea<emailSetupModalLogicType>([
    path(['products', 'messaging', 'frontend', 'EmailSetup', 'emailSetupModalLogic']),
    props({} as EmailSetupModalLogicProps),
    key(() => 'global'),
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
        setupResponse: {
            submitDomain: (domain) => {
                return api.messaging.createEmailSenderDomain(domain)
            },
        },
        verificationResponse: {
            verifyDomain: async () => {
                return api.messaging.verifyEmailSenderDomain(values.emailIntegration.domain)
            },
        },
    })),
    selectors({
        dnsRecords: [
            (s) => [s.setupResponse],
            (setupResponse: { records: DnsRecord[] } | null) => setupResponse?.records || null,
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
