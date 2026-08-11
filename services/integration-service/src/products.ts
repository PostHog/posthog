// The product names this service recognises: the code path that wanted a credential
// (`warehouse-sources`, `cdp`). Caller-supplied, never verified, and grants nothing.
//
// The list exists so an unrecognised value collapses to a constant. A caller-supplied
// string must never reach a Prometheus label, because prom-client keeps every series in
// process memory for the pod's lifetime.
//
// Keep in step with IntegrationCaller in posthog/integration_secrets/callers.py. A name
// missing here still works, and records as "unknown".

const UNKNOWN_PRODUCT = 'unknown'

const KNOWN_PRODUCTS: ReadonlySet<string> = new Set(['warehouse-sources', 'cdp', 'messaging', 'tasks', 'web-analytics'])

/** The product name if we recognise it, else a constant, so label cardinality stays bounded. */
export function productLabel(claimed: string): string {
    return KNOWN_PRODUCTS.has(claimed) ? claimed : UNKNOWN_PRODUCT
}
