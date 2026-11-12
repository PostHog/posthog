import type { AuthorizeSpec, ProviderOverride, ProviderSpec, TokenInfoSpec, TokenSpec } from './schema'

export interface SpecContext {
    /** The service environment, `CREDENTIALS_SERVICE_ENV`. */
    environment?: string
    /** The row's region, for a kind whose provider differs per region. */
    region?: string
}

/** The spec with its environment override and then its region override applied, one block deep. */
export function applyOverrides(spec: ProviderSpec, context: SpecContext): ProviderSpec {
    const layers = [
        context.environment ? spec.overrides?.environment?.[context.environment] : undefined,
        context.region ? spec.overrides?.region?.[context.region] : undefined,
    ]
    return layers.reduce<ProviderSpec>((current, layer) => (layer ? merge(current, layer) : current), spec)
}

function merge(spec: ProviderSpec, layer: ProviderOverride): ProviderSpec {
    const merged: ProviderSpec = { ...spec }
    if (layer.authorize && spec.authorize) {
        merged.authorize = { ...spec.authorize, ...(present(layer.authorize) as Partial<AuthorizeSpec>) }
    }
    if (layer.token && spec.token) {
        merged.token = { ...spec.token, ...(present(layer.token) as Partial<TokenSpec>) }
    }
    if (layer.tokenInfo && spec.tokenInfo) {
        merged.tokenInfo = { ...spec.tokenInfo, ...(present(layer.tokenInfo) as Partial<TokenInfoSpec>) }
    }
    if (layer.clientSecretKeys) {
        merged.clientSecretKeys = layer.clientSecretKeys
    }
    return merged
}

// An override key set to undefined must not erase the base value.
function present(value: object): object {
    return Object.fromEntries(Object.entries(value).filter(([, entry]) => entry !== undefined))
}
