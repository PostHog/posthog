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

const SECOND_LEVEL_SUFFIX_LABELS = new Set(['co', 'com', 'org', 'net', 'ac', 'gov', 'edu'])

const PLACEHOLDER_ORGANIZATION_NAME = /^(?:default(?: organization)?|.*['’]s organization)$/i
const PRINTABLE_ASCII = /^[\x20-\x7E]+$/
const ADDRESS_SYNTAX = /["<>\\]/

const fitsUnencodedInFromHeader = (name: string): boolean => PRINTABLE_ASCII.test(name) && !ADDRESS_SYNTAX.test(name)

const isUsableOrganizationName = (name: string): boolean =>
    Boolean(name) && !PLACEHOLDER_ORGANIZATION_NAME.test(name) && fitsUnencodedInFromHeader(name)

const isCountryCodeSuffix = (labels: string[]): boolean => {
    const [secondLevel, topLevel] = labels.slice(-2)
    return topLevel?.length === 2 && SECOND_LEVEL_SUFFIX_LABELS.has(secondLevel)
}

const brandLabelOf = (domain: string): string => {
    const labels = domain.split('.').filter(Boolean)
    const suffixLength = labels.length > 2 && isCountryCodeSuffix(labels) ? 2 : 1
    return labels.at(-suffixLength - 1) ?? domain
}

const capitalize = (label: string): string => label.charAt(0).toUpperCase() + label.slice(1)

export const defaultSenderName = (organizationName: string | null | undefined, domain: string): string => {
    const name = organizationName?.trim() ?? ''
    return isUsableOrganizationName(name) ? name : capitalize(brandLabelOf(domain))
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
