// The public part of the registry, as `posthog/integrations/catalogue_generated.json`. Django reads
// it to list kinds and to build authorize URLs. It holds platform-secret names, never their values.

import { type AuthorizeParam, authorizeParams } from './authorize'
import { legacySecretName } from './defaults'
import { applyOverrides, type SpecContext } from './overrides'
import type { AuthType, ProviderSpec } from './schema'

export const CATALOGUE_NOTICE =
    'Generated from services/credentials-service/src/providers. Do not edit. Run `hogli build:projections --only credentials-catalogue`.'

export interface CatalogueAuthorize {
    url: string
    /** Ordered. A value in braces is a placeholder that Django fills: client_id, redirect_uri, state, code_challenge. */
    params: AuthorizeParam[]
    scope: string
    pkce: boolean
    opaque_state: boolean
    /** The platform secret that holds the client id. */
    client_id_key: string | null
    /** Platform settings that fill the `{name}` placeholders in `url`. */
    url_values: Record<string, string>
}

export interface CatalogueKind {
    label: string
    auth_types: { default: AuthType; others: AuthType[] }
    authorize: CatalogueAuthorize | null
    /** The whole authorize block for an environment that overrides it, for example `dev`. */
    authorize_by_environment: Record<string, CatalogueAuthorize>
    authorize_by_region: Record<string, CatalogueAuthorize>
    display_name: { config_paths: string[]; when_missing: string | null }
}

export interface Catalogue {
    notice: string
    kinds: Record<string, CatalogueKind>
}

export function buildCatalogue(specs: readonly ProviderSpec[]): Catalogue {
    const kinds: Record<string, CatalogueKind> = {}
    for (const spec of [...specs].sort((a, b) => a.kind.localeCompare(b.kind))) {
        kinds[spec.kind] = {
            label: spec.label,
            auth_types: { default: spec.authTypes.default, others: [...spec.authTypes.others].sort() },
            authorize: catalogueAuthorize(spec),
            authorize_by_environment: overridden(spec, spec.overrides?.environment, (environment) => ({ environment })),
            authorize_by_region: overridden(spec, spec.overrides?.region, (region) => ({ region })),
            display_name: {
                config_paths: spec.displayName.configPaths,
                when_missing: spec.displayName.whenMissing ?? null,
            },
        }
    }
    return { notice: CATALOGUE_NOTICE, kinds }
}

function overridden(
    spec: ProviderSpec,
    overrides: Record<string, unknown> | undefined,
    context: (key: string) => SpecContext
): Record<string, CatalogueAuthorize> {
    const result: Record<string, CatalogueAuthorize> = {}
    for (const key of Object.keys(overrides ?? {}).sort()) {
        const authorize = catalogueAuthorize(applyOverrides(spec, context(key)))
        if (authorize) {
            result[key] = authorize
        }
    }
    return result
}

function catalogueAuthorize(spec: ProviderSpec): CatalogueAuthorize | null {
    const authorize = spec.authorize
    if (!authorize) {
        return null
    }
    return {
        url: authorize.url,
        params: authorizeParams(authorize),
        scope: authorize.scope,
        pkce: authorize.pkce,
        opaque_state: authorize.opaqueState,
        // Django settings keep the unprefixed names, so the Python catalogue does too.
        client_id_key: spec.clientSecretKeys ? legacySecretName(spec.clientSecretKeys.clientId) : null,
        url_values: authorize.urlValues ?? {},
    }
}
