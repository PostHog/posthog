export type RegionId = 'us' | 'eu' | 'custom'

export interface Region {
    id: RegionId
    label: string
    host: string
    clientId: string
}

export const US_CLIENT_ID = 'a5TY7w9IjFYfes6dkPgZe6envclWw3bm2UD8ZTlm'
export const EU_CLIENT_ID = '1A7vO138Fh5sYmJislicN4F5HnttI6urmFttxPDU'
// The OAuth app that `setup_tasks_oauth` creates for a local stack, so a dev build signs in there without typing an id.
export const DEV_CLIENT_ID = 'DC5uRLVbGI02YQ82grxgnK6Qn12SXWpCqdPb60oZ'

export const REGIONS: readonly Region[] = [
    { id: 'us', label: 'US', host: 'https://us.posthog.com', clientId: US_CLIENT_ID },
    { id: 'eu', label: 'EU', host: 'https://eu.posthog.com', clientId: EU_CLIENT_ID },
    { id: 'custom', label: 'Custom', host: '', clientId: '' },
]

export function regionForHost(host: string): RegionId {
    return REGIONS.find((region) => region.host !== '' && region.host === host)?.id ?? 'custom'
}

export type HostValidation = { ok: true; host: string } | { ok: false; error: string }

function isLoopback(hostname: string): boolean {
    const bare = hostname.replace(/^\[|\]$/g, '').toLowerCase()
    return bare === 'localhost' || bare === '::1' || /^127(\.\d{1,3}){3}$/.test(bare)
}

// Tokens travel to this host, so plain http is only accepted for loopback addresses, which is also the only place the
// server allows http redirects.
export function validateHost(input: string): HostValidation {
    const trimmed = input.trim().replace(/\/+$/, '')
    if (!trimmed) {
        return { ok: false, error: 'Enter the address of your PostHog instance.' }
    }
    const withScheme = /^[a-z][a-z\d+.-]*:\/\//i.test(trimmed) ? trimmed : `https://${trimmed}`
    let url: URL
    try {
        url = new URL(withScheme)
    } catch {
        return { ok: false, error: "That doesn't look like a web address. Try something like posthog.example.com." }
    }
    if (!url.hostname) {
        return { ok: false, error: "That doesn't look like a web address. Try something like posthog.example.com." }
    }
    if (url.protocol === 'http:' && !isLoopback(url.hostname)) {
        return { ok: false, error: 'Use an https address. Plain http only works for localhost.' }
    }
    if (url.protocol !== 'https:' && url.protocol !== 'http:') {
        return { ok: false, error: 'Use an https address, for example https://posthog.example.com.' }
    }
    return { ok: true, host: `${url.protocol}//${url.host}` }
}
