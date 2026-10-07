import { useValues } from 'kea'

import { IconWarning } from '@posthog/icons'
import { Link } from '@posthog/lemon-ui'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { humanFriendlyNumber } from 'lib/utils/numbers'
import { matchingActorsUrl } from 'scenes/feature-flags/matchingActorsUrl'

import { AnyPropertyFilter, HogQLPropertyFilter, PropertyFilterType } from '~/types'

/** Mirrors `email_missing_expr` in the backend, so the list holds exactly the people the warning counts. */
const HAS_NO_EMAIL: HogQLPropertyFilter = {
    type: PropertyFilterType.HogQL,
    key: "isNull(properties.email) OR trim(toString(properties.email)) = ''",
}

export function AudienceWithoutEmailNotice({
    withoutEmail,
    audienceProperties,
}: {
    withoutEmail: number | null
    audienceProperties: AnyPropertyFilter[]
}): JSX.Element | null {
    const { featureFlags } = useValues(featureFlagLogic)
    if (!featureFlags[FEATURE_FLAGS.WORKFLOWS_MISSING_EMAIL_WARNING] || !withoutEmail) {
        return null
    }

    return (
        <div className="text-warning text-xs flex items-start gap-1 mt-1">
            <IconWarning className="text-base shrink-0 mt-0.5" />
            <div>
                <div>{describeWithoutEmail(withoutEmail)}</div>
                <div className="text-secondary">
                    Add an email property to them, or{' '}
                    <Link
                        to={matchingActorsUrl([...audienceProperties, HAS_NO_EMAIL], null)}
                        target="_blank"
                        data-attr="audience-without-email-link"
                    >
                        view who is affected
                    </Link>
                    .
                </div>
            </div>
        </div>
    )
}

function describeWithoutEmail(withoutEmail: number): string {
    if (withoutEmail === 1) {
        return '1 person in this audience has no email address and will not get the email.'
    }
    return `About ${humanFriendlyNumber(withoutEmail)} people in this audience have no email address and will not get the email.`
}
