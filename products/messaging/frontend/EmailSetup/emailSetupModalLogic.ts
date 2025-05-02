import { kea, key, listeners, path, props, selectors } from 'kea'
import { forms } from 'kea-forms'
import { loaders } from 'kea-loaders'
import api from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast'

import { IntegrationType } from '~/types'

import type { emailSetupModalLogicType } from './emailSetupModalLogicType'

export interface EmailSetupModalLogicProps {
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

// Using 'any' temporarily until typegen runs
export const emailSetupModalLogic = kea<emailSetupModalLogicType>([
    path(['products', 'messaging', 'frontend', 'EmailSetup', 'emailSetupModalLogic']),
    props({} as EmailSetupModalLogicProps),
    key(() => 'global'),
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
    loaders(({ values }) => ({
        integration: {
            setIntegration: (integration: IntegrationType) => integration,
            submitDomain: () => {
                return api.integrations.create({
                    kind: 'email',
                    config: {
                        domain: values.emailSender.domain,
                    },
                })
            },
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
        submitDomainSuccess: () => {
            // Fetch the DNS records and current verification status
            actions.verifyDomain()
        },
        verifyDomainSuccess: ({ verification }) => {
            if (verification.status === 'success') {
                lemonToast.success('Domain verified successfully!')
                props.onComplete(values.integration.id)
            }
        },
    })),
])
