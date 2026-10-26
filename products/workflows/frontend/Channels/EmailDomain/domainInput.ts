const FREE_MAILBOX_DOMAINS = new Set([
    'gmail.com',
    'googlemail.com',
    'outlook.com',
    'hotmail.com',
    'live.com',
    'yahoo.com',
    'icloud.com',
    'me.com',
    'proton.me',
    'protonmail.com',
    'web.de',
])

const DOMAIN_PATTERN = /^[a-z0-9](?:[a-z0-9-]*[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]*[a-z0-9])?)*\.[a-z]{2,}$/

export interface NormalizedDomainInput {
    domain: string
    localPart: string | null
}

export const normalizeDomainInput = (raw: string): NormalizedDomainInput => {
    let value = raw.trim().toLowerCase()
    let localPart: string | null = null
    if (value.includes('@')) {
        const [local, host] = value.split('@')
        localPart = local || null
        value = host ?? ''
    }
    value = value.replace(/^[a-z]+:\/\//, '')
    value = value.split('/')[0].split('?')[0].split(':')[0]
    value = value.replace(/^www\./, '')
    return { domain: value, localPart }
}

export const isFreeMailboxDomain = (domain: string): boolean =>
    FREE_MAILBOX_DOMAINS.has(domain) || domain.startsWith('gmx.')

export const isValidDomain = (domain: string): boolean => DOMAIN_PATTERN.test(domain)

export const rootDomainOf = (hostname: string): string => hostname.split('.').filter(Boolean).slice(-2).join('.')

export const nameFromDomain = (domain: string): string => {
    const label = domain.split('.').filter(Boolean).slice(-2)[0] ?? domain
    return label ? label.charAt(0).toUpperCase() + label.slice(1) : ''
}

export const hostnameOfUrl = (url: string): string | null => {
    try {
        const hostname = new URL(url.includes('://') ? url : `https://${url}`).hostname.toLowerCase()
        return hostname.replace(/^www\./, '')
    } catch {
        return null
    }
}

export type DomainProblem = 'free_mailbox' | 'invalid'

export const domainProblemOf = (domain: string): DomainProblem | null => {
    if (!domain) {
        return null
    }
    if (isFreeMailboxDomain(domain)) {
        return 'free_mailbox'
    }
    if (!isValidDomain(domain)) {
        return 'invalid'
    }
    return null
}

export const asSubdomainLabel = (value: string): string => value.toLowerCase().replace(/[^a-z0-9-]/g, '')
