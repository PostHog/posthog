import { LemonBanner } from '@posthog/lemon-ui'

import { humanFriendlyNumber } from 'lib/utils/numbers'

export interface MissingRecipientEmailBannerProps {
    /** The person property the To field reads. */
    property: string
    /** How many people in the audience have no value for it. */
    missing: number
    /** The audience size, when known. A missing count at or above it means nobody has the property. */
    audienceSize?: number
}

export function MissingRecipientEmailBanner({
    property,
    missing,
    audienceSize,
}: MissingRecipientEmailBannerProps): JSX.Element | null {
    if (missing <= 0) {
        return null
    }
    const code = <code>{property}</code>
    const nobody = audienceSize != null && missing >= audienceSize

    return (
        <LemonBanner type="warning">
            {nobody ? (
                <>Nobody in this audience has the {code} property, so this email won't reach anyone. </>
            ) : (
                <>
                    About {humanFriendlyNumber(missing)} people in this audience have no {code} property, so they won't
                    get this email.{' '}
                </>
            )}
            {property === 'email' ? (
                <>
                    If your people store their address in <code>$email</code>, set the To field to{' '}
                    <code>{'{{ person.properties.$email }}'}</code>.
                </>
            ) : (
                <>Set the To field to the property that holds their email address.</>
            )}
        </LemonBanner>
    )
}
