// Reads of non-secret row config that a spec drives. Ports of `common.dot_get`, the display name
// branches of `Integration.display_name` and `_salesforce_instance_host`.

import type { ProviderSpec, TokenSpec } from './schema'

/**
 * `common.dot_get`: a literal key that holds the whole path wins, so token info fields stored
 * under their dotted names (Linear's `data.viewer.organization.id`) read back. Otherwise walk the
 * path one key at a time.
 */
export function dotGet(value: unknown, path: string): unknown {
    if (isObject(value) && value[path] !== undefined && value[path] !== null) {
        return value[path]
    }
    let current: unknown = value
    for (const key of path.split('.')) {
        if (!isObject(current)) {
            return undefined
        }
        current = current[key]
    }
    return current
}

/**
 * The row's name in the UI. A row whose auth type is not the kind's default stores its own
 * `display_name`, because the spec's paths read the config shape of the default auth type.
 */
export function displayName(
    spec: ProviderSpec,
    row: { config: Readonly<Record<string, unknown>>; externalId: string | null; authType: string }
): string {
    if (row.authType !== spec.authTypes.default) {
        const own = row.config['display_name']
        return typeof own === 'string' && own ? own : `ID: ${row.externalId ?? ''}`
    }
    for (const path of spec.displayName.configPaths) {
        const value = dotGet(row.config, path)
        if (value !== undefined && value !== null) {
            return String(value)
        }
    }
    return row.externalId || (spec.displayName.whenMissing ?? '')
}

/**
 * `https://<host>` from the config field that `tokenHost` names, or null when the value is not
 * a plain https URL on the allowed host suffix. The caller then uses the spec's fixed URLs.
 */
export function tokenHostBaseUrl(token: TokenSpec, config: Readonly<Record<string, unknown>>): string | null {
    const rule = token.tokenHost
    const raw = rule ? config[rule.fromConfig] : undefined
    if (!rule || typeof raw !== 'string' || !raw) {
        return null
    }
    let url: URL
    try {
        url = new URL(raw)
    } catch {
        return null
    }
    // Python rejects any explicit port, the default one too. WHATWG URL drops a default port, so check the raw text.
    const authority = raw.slice(raw.indexOf('//') + 2).split(/[/?#]/, 1)[0] ?? ''
    if (url.protocol !== 'https:' || url.username || url.password || /:\d*$/.test(authority)) {
        return null
    }
    const host = url.hostname.toLowerCase()
    return rule.allow.some((suffix) => host.endsWith(suffix)) ? `https://${host}` : null
}

function isObject(value: unknown): value is Record<string, unknown> {
    return typeof value === 'object' && value !== null && !Array.isArray(value)
}

/**
 * Whether a row's region may exist in this service environment. A region with no rule is allowed
 * everywhere. A row with no region is never blocked.
 */
export function regionAllowed(spec: ProviderSpec, region: string | undefined, environment: string): boolean {
    const rule = region ? spec.regions?.[region] : undefined
    return !rule || rule.allowedIn.includes(environment)
}

/**
 * The keys of a config `PATCH` that only create and exchange may set. The CRUD route refuses a non-empty result.
 * A dotted key counts too, because `dotGet` reads a literal `team.id` before the protected `team`.
 */
export function touchesIdentityConfig(spec: ProviderSpec, patch: Readonly<Record<string, unknown>>): string[] {
    return Object.keys(patch).filter((key) =>
        spec.identityConfigKeys.some(
            (protectedKey) =>
                key === protectedKey || key.startsWith(`${protectedKey}.`) || protectedKey.startsWith(`${key}.`)
        )
    )
}
