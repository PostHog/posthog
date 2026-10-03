import { IconWarning } from '@posthog/icons'
import { Link } from '@posthog/lemon-ui'

import { humanFriendlyNumber } from 'lib/utils/numbers'

import { AnyPropertyFilter } from '~/types'

import { audienceWithoutEmailUrl } from './audienceWithoutEmailUrl'

export function AudienceWithoutEmailNotice({
    withoutEmail,
    audienceProperties,
}: {
    withoutEmail: number | null
    audienceProperties: AnyPropertyFilter[]
}): JSX.Element | null {
    if (!withoutEmail) {
        return null
    }

    const subject = withoutEmail === 1 ? '1 person' : `${humanFriendlyNumber(withoutEmail)} people`
    const verb = withoutEmail === 1 ? 'has' : 'have'
    return (
        <div className="text-warning text-xs flex items-start gap-1 mt-1">
            <IconWarning className="text-base shrink-0 mt-0.5" />
            <div>
                <div>{`${subject} in this audience ${verb} no email address and will not get the email.`}</div>
                <div className="text-secondary">
                    Set the email property, for example by calling identify() with an email, or{' '}
                    <Link to={audienceWithoutEmailUrl(audienceProperties)} data-attr="audience-without-email-link">
                        view who is affected
                    </Link>
                    .
                </div>
            </div>
        </div>
    )
}
