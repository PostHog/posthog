import { IntegrationType } from '~/types'

export type PushIdentityVerificationMode = 'disabled' | 'optional' | 'required'

export const PUSH_IDENTITY_VERIFICATION_MODES: PushIdentityVerificationMode[] = ['disabled', 'optional', 'required']

export const PUSH_IDENTITY_VERIFICATION_DEFAULT: PushIdentityVerificationMode = 'disabled'

/**
 * Seed the form from what the integration already has. Reconnecting to rotate credentials submits
 * this field like any other, so defaulting to `disabled` would silently turn verification off for a
 * channel that had it on — the backend can't tell that apart from someone deliberately disabling it.
 */
export function resolvePushIdentityVerification(integration?: IntegrationType | null): PushIdentityVerificationMode {
    const stored = integration?.config?.push_identity_verification
    return PUSH_IDENTITY_VERIFICATION_MODES.includes(stored) ? stored : PUSH_IDENTITY_VERIFICATION_DEFAULT
}

/**
 * Config fragment to merge into the create payload. Sending the key at all counts as changing the
 * policy and requires project admin, so an unchanged field is omitted — that lets a member connect or
 * reconnect a channel, and leaves the stored policy for the backend to carry forward.
 */
export function pushIdentityVerificationPayload(
    mode: PushIdentityVerificationMode,
    integration?: IntegrationType | null
): { push_identity_verification?: PushIdentityVerificationMode } {
    return mode === resolvePushIdentityVerification(integration) ? {} : { push_identity_verification: mode }
}

/**
 * Seed the public-key field from the stored key. The backend keeps up to two (for rotation); the UI
 * edits the primary one, so an empty field means "no key registered".
 */
export function resolvePushIdentityPublicKey(integration?: IntegrationType | null): string {
    const stored = integration?.config?.push_identity_public_keys
    return Array.isArray(stored) && typeof stored[0] === 'string' ? stored[0] : ''
}

/**
 * Config fragment for the public key. Like the mode, an unchanged field is omitted so reconnecting a
 * channel carries the stored key forward; a non-empty value registers/replaces it, an empty one clears it.
 */
export function pushIdentityPublicKeysPayload(
    publicKey: string,
    integration?: IntegrationType | null
): { push_identity_public_keys?: string[] } {
    const trimmed = publicKey.trim()
    if (trimmed === resolvePushIdentityPublicKey(integration)) {
        return {}
    }
    return { push_identity_public_keys: trimmed ? [trimmed] : [] }
}

/** Verification checks tokens against the registered public key only, so `required` needs one to accept any device. */
export function pushIdentityPublicKeyError(mode: PushIdentityVerificationMode, publicKey: string): string | undefined {
    return mode === 'required' && !publicKey.trim() ? 'Public key is required to verify identity tokens' : undefined
}
