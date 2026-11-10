import { LemonBanner } from '@posthog/lemon-ui'

import { humanFriendlyNumber } from 'lib/utils/numbers'

const LOUD_MISSING_SHARE = 0.1

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
    const code = <code className="break-words">{property}</code>
    const nobody = audienceSize != null && missing >= audienceSize
    const fix =
        property === 'email' ? (
            <>
                Set the To field to <code className="whitespace-nowrap">{"{{ person.properties['$email'] }}"}</code> if
                their address is in <code>$email</code>.
            </>
        ) : (
            <>Set the To field to the property that holds their email address.</>
        )

    if (nobody) {
        return (
            <LemonBanner type="warning">
                Nobody in this audience has the {code} property, so this email won't reach anyone. {fix}
            </LemonBanner>
        )
    }

    const message = (
        <>
            About {humanFriendlyNumber(missing)} people in this audience have no {code} property, so they won't get this
            email.{' '}
        </>
    )

    // A large audience almost always has a few people without an address, so that case gets a quiet note.
    // The warning banner is for a share large enough to point at a wrong To field or audience.
    if (audienceSize == null || missing / audienceSize >= LOUD_MISSING_SHARE) {
        return (
            <LemonBanner type="warning">
                {message}
                {fix}
            </LemonBanner>
        )
    }

    return (
        <div className="text-xs text-secondary">
            {message}
            {fix}
        </div>
    )
}
