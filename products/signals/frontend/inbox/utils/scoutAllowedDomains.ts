import type { SignalScoutConfigApi } from 'products/signals/frontend/generated/api.schemas'

// Matches `MAX_SANDBOX_ALLOWED_DOMAINS` in products/tasks/backend/logic/services/network_policy.py.
export const MAX_SCOUT_ALLOWED_DOMAINS = 100
export const MAX_SCOUT_ALLOWED_DOMAIN_LENGTH = 255

// The reasons the sandbox rejects a domain, checked here so a typo is caught before the request
// instead of coming back as a toast. `normalize_domain` on the backend stays the authority; the
// URL parser gives the same IDNA (punycode) form it stores, so a Unicode name passes here too.
const DOMAIN_LABELS = /^[a-z0-9](?:[a-z0-9-]*[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]*[a-z0-9])?)+$/
const IPV4 = /^\d{1,3}(?:\.\d{1,3}){3}$/
// A scheme, port, path, query, or userinfo. Checked on the raw text because the URL parser would
// otherwise strip them and hand back a hostname the person never typed.
const NOT_A_BARE_HOST = /[/:?#@\s]/
const LOCAL_HOSTS = new Set(['localhost', 'host.docker.internal'])

function idnaHostname(host: string): string | null {
    try {
        return new URL(`http://${host}`).hostname
    } catch {
        return null
    }
}

/** The domain as the sandbox would store it, or null when it could never be a domain. */
export function normalizeScoutDomain(raw: string): string | null {
    const trimmed = raw.trim().toLowerCase().replace(/\.$/, '')
    if (!trimmed || trimmed.length > MAX_SCOUT_ALLOWED_DOMAIN_LENGTH || NOT_A_BARE_HOST.test(trimmed)) {
        return null
    }
    const wildcard = trimmed.startsWith('*.')
    const hostname = idnaHostname(wildcard ? trimmed.slice(2) : trimmed)
    if (!hostname || LOCAL_HOSTS.has(hostname) || IPV4.test(hostname) || !DOMAIN_LABELS.test(hostname)) {
        return null
    }
    return wildcard ? `*.${hostname}` : hostname
}

export interface ParsedScoutAllowedDomains {
    domains: string[]
    invalid: string[]
}

/** Split a pasted or typed entry on commas and whitespace, so a whole list can go in at once. */
export function parseScoutAllowedDomainsInput(input: string): ParsedScoutAllowedDomains {
    const domains: string[] = []
    const invalid: string[] = []

    for (const candidate of input.split(/[\s,]+/)) {
        if (!candidate.trim()) {
            continue
        }
        const domain = normalizeScoutDomain(candidate)
        if (!domain) {
            invalid.push(candidate.trim())
        } else if (!domains.includes(domain)) {
            domains.push(domain)
        }
    }

    return { domains, invalid }
}

export function scoutAllowedDomains(config: Pick<SignalScoutConfigApi, 'allowed_domains'>): string[] {
    return [...(config.allowed_domains ?? [])]
}

export interface ScoutAllowedDomainsAddition {
    domains: string[] | null
    overCap: boolean
}

export function withScoutDomainsAdded(existing: string[], additions: string[]): ScoutAllowedDomainsAddition {
    // Insertion order, not sorted: the list is short and a person reads it back in the order they
    // built it. The backend preserves the order it is given.
    const next = [...existing, ...additions.filter((domain) => !existing.includes(domain))]
    if (next.length > MAX_SCOUT_ALLOWED_DOMAINS) {
        return { domains: null, overCap: true }
    }
    if (next.length === existing.length) {
        return { domains: null, overCap: false }
    }
    return { domains: next, overCap: false }
}

export function withScoutDomainRemoved(existing: string[], domain: string): string[] | null {
    if (!existing.includes(domain)) {
        return null
    }
    return existing.filter((candidate) => candidate !== domain)
}
