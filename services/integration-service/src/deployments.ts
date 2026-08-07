// Who may call this service, and what each one may reach.
//
// Two separate ideas, deliberately not conflated:
//
//   DEPLOYMENT — the pod set holding a signing key (`posthog-django`, a temporal
//   worker). This is the authenticated identity: it is derived from *which key
//   verified the token*, never from a claim, so it cannot be asserted by the caller.
//   Its provider list is the authorization boundary.
//
//   PRODUCT — the code path inside that deployment that wanted the credential
//   (`warehouse-sources`, `cdp`). Caller-supplied and NOT verified: Django holds one
//   key and hosts many products, so a compromised Django pod could name any of them.
//   It exists for metrics and audit, and is listed here only so an unrecognised value
//   collapses to a constant rather than becoming an unbounded metric label.
//
// Both live in code rather than in Secrets Manager. This is authorization policy, so
// it should move through review, and it changes rarely.

/** Providers a deployment may reach, or ALL_PROVIDERS where narrowing would be false precision. */
export const ALL_PROVIDERS = '*' as const

export const DEPLOYMENT_PROVIDERS: Readonly<Record<string, readonly string[] | typeof ALL_PROVIDERS>> = {
    // Django hosts nearly every product, so an explicit list here would be the full set
    // with extra maintenance. The honest value is the wildcard.
    'posthog-django': ALL_PROVIDERS,
    // The warehouse worker is the opposite case: a genuinely narrow need, so the list is
    // worth its upkeep. It changes when the warehouse team adds a source, in the same PR
    // that adds the source.
    'temporal-worker-data-warehouse': [
        'bing-ads',
        'google-ads',
        'google-analytics',
        'google-search-console',
        'google-sheets',
        'hubspot',
        'linkedin-ads',
        'meta-ads',
        'resend',
        'salesforce',
        'stripe',
        'tiktok-ads',
        'youtube-analytics',
    ],
}

/** Label used when a caller names a product this service does not recognise. */
const UNKNOWN_PRODUCT = 'unknown'

// Product names accepted as a metric label. Not an authorization list — see the note
// above. Keep in step with IntegrationCaller in posthog/integration_secrets/callers.py.
const KNOWN_PRODUCTS: ReadonlySet<string> = new Set(['warehouse-sources', 'cdp', 'messaging', 'tasks', 'web-analytics'])

/** The product name if we recognise it, else a constant, so label cardinality stays bounded. */
export function productLabel(claimed: string): string {
    return KNOWN_PRODUCTS.has(claimed) ? claimed : UNKNOWN_PRODUCT
}
