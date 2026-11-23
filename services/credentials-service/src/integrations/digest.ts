// A salted digest of an integration row's content. The Django side computes the same digest in
// posthog/integrations/mirror/canonical.py, so the two stores can be reconciled without plaintext
// leaving the service. tests/fixtures/content-digest-vectors.json pins both implementations.
// canonicalJson prints strings as JSON.stringify does, so a lone surrogate becomes `\udxxx` where
// RFC 8785 would reject it. The Python side also rejects an integer a double cannot hold exactly,
// which JSON.parse would already have rounded here.

import { createHmac } from 'node:crypto'

import { type JsonObject, canonicalJson } from '../crypto/canonical'

export const CONTENT_DIGEST_VERSION = 1

export interface DigestParts {
    config: JsonObject
    errors: string
    externalId: string | null
    sensitiveConfig: JsonObject
    unreadableKeys: readonly string[]
}

export function contentDigestPayload(parts: DigestParts): JsonObject {
    return {
        v: CONTENT_DIGEST_VERSION,
        config: parts.config,
        errors: parts.errors,
        external_id: parts.externalId,
        sensitive_config: parts.sensitiveConfig,
        // Array.sort compares UTF-16 code units, the same order canonicalJson uses for keys.
        unreadable_keys: [...parts.unreadableKeys].sort(),
    }
}

/** Lowercase hex HMAC-SHA256, keyed by `salt`, of the canonical JSON of the row content. */
export function contentDigest(salt: Buffer, parts: DigestParts): string {
    if (salt.length === 0) {
        throw new TypeError('content digest salt must not be empty')
    }
    return createHmac('sha256', salt)
        .update(canonicalJson(contentDigestPayload(parts)), 'utf8')
        .digest('hex')
}
