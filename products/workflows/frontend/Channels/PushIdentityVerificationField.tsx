import { LemonSegmentedButton } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'

export type PushIdentityVerificationMode = 'disabled' | 'optional' | 'required'

export const PUSH_IDENTITY_VERIFICATION_DEFAULT: PushIdentityVerificationMode = 'disabled'

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
    )
}
