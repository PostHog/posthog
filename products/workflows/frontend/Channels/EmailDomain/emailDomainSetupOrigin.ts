import { Scene } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { Breadcrumb } from '~/types'

export type EmailDomainSetupOrigin = 'workflows' | 'transactional'

export interface EmailDomainSetupOriginConfig {
    backLabel: string
    backUrl: string
    // pinned: data-attr, autocapture and Playwright select the back link by it
    backDataAttr: string
    breadcrumbs: Breadcrumb[]
}

export const DEFAULT_EMAIL_DOMAIN_SETUP_ORIGIN: EmailDomainSetupOrigin = 'workflows'

// pinned: URL search param, links and the Domain Connect return carry it
export const EMAIL_DOMAIN_SETUP_ORIGIN_PARAM = 'from'

export const EMAIL_DOMAIN_SETUP_ORIGINS: Record<EmailDomainSetupOrigin, EmailDomainSetupOriginConfig> = {
    workflows: {
        backLabel: 'Back to workflows',
        backUrl: urls.workflows('channels'),
        backDataAttr: 'email-domain-back-to-workflows',
        breadcrumbs: [
            { key: Scene.Workflows, name: 'Workflows', path: urls.workflows(), iconType: 'workflows' },
            { key: 'channels', name: 'Channels', path: urls.workflows('channels'), iconType: 'workflows' },
        ],
    },
    transactional: {
        backLabel: 'Back to transactional emails',
        backUrl: urls.transactional(),
        backDataAttr: 'email-domain-back-to-transactional',
        breadcrumbs: [
            { key: Scene.Transactional, name: 'Transactional', path: urls.transactional(), iconType: 'transactional' },
        ],
    },
}

const isOrigin = (value: unknown): value is EmailDomainSetupOrigin =>
    typeof value === 'string' && Object.hasOwn(EMAIL_DOMAIN_SETUP_ORIGINS, value)

export const originFromSearchParams = (searchParams: Record<string, unknown>): EmailDomainSetupOrigin => {
    const value = searchParams[EMAIL_DOMAIN_SETUP_ORIGIN_PARAM]
    return isOrigin(value) ? value : DEFAULT_EMAIL_DOMAIN_SETUP_ORIGIN
}

export const originSearchParams = (origin: EmailDomainSetupOrigin): Record<string, string> =>
    origin === DEFAULT_EMAIL_DOMAIN_SETUP_ORIGIN ? {} : { [EMAIL_DOMAIN_SETUP_ORIGIN_PARAM]: origin }
