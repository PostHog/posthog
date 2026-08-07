// The product names this service recognises.
//
// A product is the code path that wanted a credential (`warehouse-sources`, `cdp`). The
// caller supplies it and it is NOT verified: Django holds one signing key and hosts many
// products, so a compromised Django pod could name any of them. It grants nothing.
//
// This list exists purely so an unrecognised value collapses to a constant. A
// caller-supplied string must never reach a Prometheus label, because prom-client keeps
// every series in process memory for the pod's lifetime.
//
// Keep in step with IntegrationCaller in posthog/integration_secrets/callers.py. A name
// missing here still works; it just records as "unknown".

const UNKNOWN_PRODUCT = 'unknown'

const KNOWN_PRODUCTS: ReadonlySet<string> = new Set(['warehouse-sources', 'cdp', 'messaging', 'tasks', 'web-analytics'])

/** The product name if we recognise it, else a constant, so label cardinality stays bounded. */
export function productLabel(claimed: string): string {
    return KNOWN_PRODUCTS.has(claimed) ? claimed : UNKNOWN_PRODUCT
}
