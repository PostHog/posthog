import { useValues } from 'kea'

import { LemonBanner } from '@posthog/lemon-ui'

import { humanFriendlyNumber } from 'lib/utils/numbers'

import { broadcastWizardLogic } from './broadcastWizardLogic'

export function BroadcastMissingRecipientEmailBanner(): JSX.Element | null {
    const { recipientsWithoutEmail, recipientEmailProperty, blastRadius } = useValues(broadcastWizardLogic)

    if (!recipientsWithoutEmail || !recipientEmailProperty) {
        return null
    }
    const property = <code>{recipientEmailProperty}</code>
    const nobody = !!blastRadius && recipientsWithoutEmail >= blastRadius.affected

    return (
        <LemonBanner type="warning">
            {nobody ? (
                <>Nobody in this audience has the {property} property, so this email won't reach anyone. </>
            ) : (
                <>
                    About {humanFriendlyNumber(recipientsWithoutEmail)} people in this audience have no {property}{' '}
                    property, so they won't get this email.{' '}
                </>
            )}
            {recipientEmailProperty === 'email' ? (
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
