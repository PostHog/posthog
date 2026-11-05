import { humanFriendlyNumber } from 'lib/utils/numbers'

import { hostnameOfUrl, isFreeMailboxDomain, isValidDomain, normalizeDomainInput, rootDomainOf } from './domainInput'

export interface EventHost {
    host: string
    count: number
}

export interface InferredDomain {
    domain: string
    reasons: string[]
    recommended: boolean
}

const isUsableHost = (domain: string | null): domain is string =>
    !!domain && isValidDomain(domain) && domain !== 'localhost'

class DomainCandidates {
    private reasons = new Map<string, string[]>()
    private rootWeight = new Map<string, number>()

    has(domain: string): boolean {
        return this.reasons.has(domain)
    }

    add(domain: string, reason: string, weight: number): void {
        this.reasons.set(domain, [...(this.reasons.get(domain) ?? []), reason])
        const root = rootDomainOf(domain)
        this.rootWeight.set(root, (this.rootWeight.get(root) ?? 0) + weight)
    }

    private recommendedDomain(): string | undefined {
        const topRoot = [...this.rootWeight.entries()].sort((a, b) => b[1] - a[1])[0]?.[0]
        const sameRoot = [...this.reasons.keys()].filter((domain) => rootDomainOf(domain) === topRoot)
        return sameRoot.includes(topRoot) ? topRoot : sameRoot[0]
    }

    ranked(): InferredDomain[] {
        const recommended = this.recommendedDomain()
        return [...this.reasons.entries()]
            .map(([domain, reasons]) => ({ domain, reasons, recommended: domain === recommended }))
            .sort((a, b) => Number(b.recommended) - Number(a.recommended))
    }
}

/** Domains the project probably sends from: where its events come from, the login email and the project URLs. */
export const inferDomains = (
    appUrls: string[],
    userEmail: string | null,
    eventHosts: EventHost[]
): InferredDomain[] => {
    const candidates = new DomainCandidates()
    for (const { host, count } of eventHosts) {
        const domain = hostnameOfUrl(host)
        if (isUsableHost(domain)) {
            candidates.add(
                domain,
                `${humanFriendlyNumber(count)} events came from ${domain} in the last 30 days`,
                count
            )
        }
    }
    const emailDomain = userEmail ? normalizeDomainInput(userEmail).domain : ''
    if (isUsableHost(emailDomain) && !isFreeMailboxDomain(emailDomain)) {
        candidates.add(emailDomain, `Your login is ${userEmail}`, 1)
    }
    for (const url of appUrls) {
        const domain = hostnameOfUrl(url)
        if (isUsableHost(domain) && !candidates.has(domain)) {
            candidates.add(domain, 'One of your project URLs', 1)
        }
    }
    return candidates.ranked()
}
