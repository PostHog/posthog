import { useActions, useValues } from 'kea'

import { LemonButton } from '@posthog/lemon-ui'

import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { TeamMembershipLevel } from 'lib/constants'

import { emailImpactLogic } from './emailImpactLogic'

export function LinkTrackingPrompt(): JSX.Element {
    const { linkTrackingTurningOn } = useValues(emailImpactLogic)
    const { turnOnLinkTracking } = useActions(emailImpactLogic)
    const restrictedReason = useRestrictedArea({
        scope: RestrictionScope.Project,
        minimumAccessLevel: TeamMembershipLevel.Admin,
    })

    return (
        <li
            className="col-span-2 min-h-28 rounded bg-surface-secondary flex flex-col items-center justify-center gap-2 p-3 text-center"
            data-attr="email-impact-link-tracking-prompt"
        >
            <span className="font-semibold">Link tracking is off</span>
            <span className="text-xs text-secondary">It connects email clicks to the sessions they start.</span>
            <LemonButton
                type="primary"
                size="small"
                loading={linkTrackingTurningOn}
                disabledReason={restrictedReason}
                onClick={() => turnOnLinkTracking()}
                data-attr="email-impact-turn-on-link-tracking"
            >
                Turn on for project
            </LemonButton>
        </li>
    )
}
