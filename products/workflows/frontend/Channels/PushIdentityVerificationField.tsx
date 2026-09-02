import { LemonSegmentedButton, LemonTextArea } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'

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

const MODE_HELP: Record<PushIdentityVerificationMode, string> = {
    disabled: 'Any client with your project API key can register a device for any user.',
    optional:
        'Tokens are checked and recorded, but devices can still register without one. Use this to confirm your app sends valid tokens before you require them.',
    required:
        'Devices without a valid token cannot register or unregister. Switch to this only once your app sends tokens, otherwise registration stops working.',
}

/**
 * Shared by the Firebase and APNs setup modals: both write the same
 * `push_identity_verification` key, which the device registration endpoint reads.
 */
export function PushIdentityVerificationField({ mode }: { mode: PushIdentityVerificationMode }): JSX.Element {
    return (
        <>
            <LemonField
                name="identityVerification"
                label="Identity verification"
                info="A device token says where to deliver a notification, not who the device belongs to. Turn this on to have your backend sign a short-lived token for the logged-in user, which your app sends when registering the device."
                help={MODE_HELP[mode]}
            >
                <LemonSegmentedButton
                    options={[
                        { value: 'disabled', label: 'Disabled' },
                        { value: 'optional', label: 'Optional' },
                        { value: 'required', label: 'Required' },
                    ]}
                    fullWidth
                />
            </LemonField>
            {mode !== 'disabled' && (
                <LemonField
                    name="identityPublicKey"
                    label="Public key"
                    info="Paste the EC (P-256) public key that pairs with your backend's signing key. Your backend signs each identity token (ES256) with the private key; PostHog verifies it with this public key, which never leaves your control. Leave blank to instead verify with your project's Feature flags secure API key (HS256)."
                >
                    <LemonTextArea
                        placeholder={'-----BEGIN PUBLIC KEY-----\n...\n-----END PUBLIC KEY-----'}
                        minRows={4}
                    />
                </LemonField>
            )}
        </>
    )
}
