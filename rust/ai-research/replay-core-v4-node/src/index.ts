/* eslint-disable @typescript-eslint/no-var-requires */
// The native addon is built from `src/lib.rs` and copied to `index.node` at the package root.
const native = require('../index.node')

/**
 * The politeness unit for a host: the registrable domain, or the host itself when it has none.
 *
 * The fetch lane rate limits by this value and the fetch topic keys on it, so both must get the
 * same answer from one public suffix list, which is why the value comes from the Rust crate. The
 * private section of that list keeps `user.github.io` and `d111.cloudfront.net` out of a shared
 * budget with the other tenants of the same provider.
 *
 * An IP literal has no registrable domain and comes back unchanged, because the address is the
 * operator.
 */
export function politenessKey(host: string): string {
    return native.politenessKey(host)
}

/**
 * Whether the fetch lane may send a request to a host.
 *
 * The recorder applies this rule before a URL reaches the topic. A redirect target has not been
 * through it, so the fetcher calls the same function rather than deriving a second answer.
 *
 * It refuses a private or reserved address, a single-label name, and a name under a suffix that
 * resolves only inside one network, which is the split-horizon DNS case.
 */
export function isPublicHost(host: string): boolean {
    return native.isPublicHost(host)
}

export interface CanonicalUrl {
    fetch: string
    dedup: string
    host: string
    domain: string
}

/** The labels of the Rust `Decline` enum. The fetch lane reports them as metric reasons. */
export type UrlPolicyDecline =
    | 'too_long'
    | 'not_absolute'
    | 'bad_scheme'
    | 'bad_port'
    | 'no_host'
    | 'non_public_host'
    | 'credential'
    | 'invalid_query'
    | 'tracking_beacon'

/**
 * The canonical forms of a URL the policy accepts, or the rule that refused it. `unwanted` is true
 * when the URL is well formed and safe but nobody wants it fetched, so a queue consumer drops only
 * that job instead of rejecting the record that carries it.
 */
export type UrlPolicyVerdict =
    | { ok: true; url: CanonicalUrl }
    | { ok: false; decline: UrlPolicyDecline; unwanted: boolean }

export function tryCanonicalizeUrl(url: string): UrlPolicyVerdict {
    const result = native.tryCanonicalizeUrl(url)
    if (typeof result.decline === 'string') {
        return {
            ok: false,
            decline: result.decline,
            unwanted: result.unwanted === true,
        }
    }
    return { ok: true, url: result }
}

export function canonicalizeUrl(url: string): CanonicalUrl | null {
    const verdict = tryCanonicalizeUrl(url)
    return verdict.ok ? verdict.url : null
}
