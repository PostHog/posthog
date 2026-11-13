import { useActions, useValues } from 'kea'

import { LemonButton } from '@posthog/lemon-ui'

import { humanFriendlyNumber } from 'lib/utils/numbers'

import { broadcastWizardLogic } from '../broadcastWizardLogic'

/** Offers the sending rate limit that lets an email audience over the normal limit go out. */
export function BroadcastRateLimitSuggestion(): JSX.Element | null {
    const { rateLimitNeeded, rateLimitMessage, emailRateLimit, blastRadius } = useValues(broadcastWizardLogic)
    const { applySuggestedRateLimit } = useActions(broadcastWizardLogic)

    if (!rateLimitNeeded || !blastRadius) {
        return null
    }
    const { maxPerHour, days } = rateLimitNeeded

    return (
        <div className="flex flex-wrap items-center gap-2 text-xs" data-attr="broadcast-rate-limit-suggestion">
            <span className={emailRateLimit ? 'text-danger' : 'text-secondary'}>
                {emailRateLimit
                    ? rateLimitMessage
                    : `This is over the project's limit of ${humanFriendlyNumber(blastRadius.limit)} people per broadcast. At ${humanFriendlyNumber(maxPerHour)} emails per hour, it reaches everyone in about ${days} ${days === 1 ? 'day' : 'days'}.`}
            </span>
            <LemonButton
                size="xsmall"
                type="secondary"
                onClick={applySuggestedRateLimit}
                data-attr="broadcast-use-suggested-rate-limit"
            >
                Use {humanFriendlyNumber(maxPerHour)} per hour
            </LemonButton>
        </div>
    )
}
