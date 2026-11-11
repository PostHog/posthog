// Config keys that say which external account a row belongs to. The envelope AAD does not cover
// them, so they are set once at create or exchange and never changed in place.

import { type JsonObject, canonicalJson } from '../crypto/canonical'
import { IntegrationApiError } from './errors'

const DEFAULT_IDENTITY_KEYS: readonly string[] = ['installation_id', 'instance_url', 'region']

/** The provider registry will return per-kind keys here later. */
export function identityConfigKeys(_kind: string): readonly string[] {
    return DEFAULT_IDENTITY_KEYS
}

/** Throws `validation` when `next` adds, removes or changes an identity key of `current`. */
export function assertIdentityUnchanged(kind: string, current: JsonObject, next: JsonObject): void {
    const differs = (key: string): boolean =>
        key in current !== key in next || canonicalJson(current[key] ?? null) !== canonicalJson(next[key] ?? null)
    const changed = identityConfigKeys(kind).filter(differs)
    if (changed.length > 0) {
        throw new IntegrationApiError(
            'validation',
            `these config keys identify the account and cannot be changed on an existing integration: ${changed.join(', ')}`,
            { keys: changed }
        )
    }
}
