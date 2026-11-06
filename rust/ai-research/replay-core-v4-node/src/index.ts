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

export type UrlJob = 'drop' | 'refresh' | 'fetch'

export function urlJob(nextFetchAtMs: number, storedAtMs: number | undefined, nowMs: number): UrlJob {
    return native.urlJob(nextFetchAtMs, storedAtMs, nowMs)
}

export function isUrlHistoryValue(key: string, value: string): boolean {
    return native.isUrlHistoryValue(key, value)
}

export type V4UrlAsset = 'image' | 'font'

export type V4UrlRef =
    | { scope: 'team'; asset: V4UrlAsset; teamId: number; keyMonth: string; hash: string }
    | { scope: 'public'; asset: 'font'; hash: string }

/** Parses `imageurl:v4:{team}:{YYYY-MM}:{hash}`, its `fonturl` twin and `fonturl:v4:public:{hash}`. `parseImageRef` refuses them all, so no v2 or v3 reader takes one. */
export function parseV4UrlRef(reference: string): V4UrlRef | null {
    return native.parseV4UrlRef(reference)
}

export function sealFetchedImage(teamMonthKey: Buffer, reference: string, image: Buffer): Promise<Buffer> {
    return native.sealFetchedImage(teamMonthKey, reference, image)
}

export function imageUrlHash(teamMonthKey: Buffer, url: string): string {
    return native.imageUrlHash(teamMonthKey, url)
}

/** The public font reference that a canonical fetch URL names, or `null` when its file belongs to a team. */
export function publicFontRefOf(fetchUrl: string): string | null {
    return native.publicFontRefOf(fetchUrl)
}

export function publicUrlHash(url: string): string {
    return native.publicUrlHash(url)
}
