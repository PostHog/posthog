import { isInternalBuild, isLoopbackHost } from '@/lib/environment'

export type RegionId = 'us' | 'eu' | 'custom'

export interface Region {
    id: RegionId
    label: string
    host: string
    clientId: string
}

export interface CloudRegion extends Region {
    id: Exclude<RegionId, 'custom'>
    flag: string
}

export const US_CLIENT_ID = 'a5TY7w9IjFYfes6dkPgZe6envclWw3bm2UD8ZTlm'
export const EU_CLIENT_ID = '1A7vO138Fh5sYmJislicN4F5HnttI6urmFttxPDU'
// The OAuth app that `setup_tasks_oauth` creates for a local stack, so a dev build signs in there without typing an id.
export const DEV_CLIENT_ID = 'DC5uRLVbGI02YQ82grxgnK6Qn12SXWpCqdPb60oZ'

export const CLOUD_REGIONS: readonly CloudRegion[] = [
    {
        id: 'us',
        label: 'United States',
        flag: '\u{1F1FA}\u{1F1F8}',
        host: 'https://us.posthog.com',
        clientId: US_CLIENT_ID,
    },
    {
        id: 'eu',
        label: 'European Union',
        flag: '\u{1F1EA}\u{1F1FA}',
        host: 'https://eu.posthog.com',
        clientId: EU_CLIENT_ID,
    },
]

// The id `custom` is persisted in AsyncStorage by the auth store, so it keeps its name while the label changes.
export const REGIONS: readonly Region[] = [
    ...CLOUD_REGIONS,
    { id: 'custom', label: 'Self-hosted', host: '', clientId: '' },
]

// Store review may not allow a link that leaves the app to create an account, so a build can hide it.
export const SHOW_SIGNUP_LINK = process.env.EXPO_PUBLIC_SIGNUP_LINK !== '0'

export function signupUrl(host: string): string {
    return `${host}/signup`
}

export function regionForHost(host: string): RegionId {
    return REGIONS.find((region) => region.host !== '' && region.host === host)?.id ?? 'custom'
}

export type HostValidation = { ok: true; host: string } | { ok: false; error: string }

// The dev app exists only on a developer's machine, so store builds start the Client ID field empty.
export const DEFAULT_CUSTOM_CLIENT_ID = isInternalBuild ? DEV_CLIENT_ID : ''

// Tokens travel to this host, so plain http is only accepted for loopback addresses, which is also the only place the
// server allows http redirects. Only internal builds accept it, because a local stack is a developer's setup.
export function validateHost(input: string, allowLoopbackHttp: boolean = isInternalBuild): HostValidation {
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
    if (url.protocol === 'http:' && !(allowLoopbackHttp && isLoopbackHost(url.hostname))) {
        return {
            ok: false,
            error: allowLoopbackHttp
                ? 'Use an https address. Plain http only works for localhost.'
                : 'Use an https address, for example https://posthog.example.com.',
        }
    }
    if (url.protocol !== 'https:' && url.protocol !== 'http:') {
        return { ok: false, error: 'Use an https address, for example https://posthog.example.com.' }
    }
    return { ok: true, host: `${url.protocol}//${url.host}` }
}
