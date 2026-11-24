import clsx from 'clsx'
import { useActions, useValues } from 'kea'

import { LemonButton } from '@posthog/lemon-ui'

import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { TeamMembershipLevel } from 'lib/constants'

import { emailImpactLogic } from './emailImpactLogic'

export function LinkTrackingPrompt({ spansConversion }: { spansConversion: boolean }): JSX.Element {
    const { linkTrackingSaveLoading, linkTrackingDisabledReason } = useValues(emailImpactLogic)
    const { turnOnLinkTracking } = useActions(emailImpactLogic)
    const restrictedReason = useRestrictedArea({
        scope: RestrictionScope.Project,
        minimumAccessLevel: TeamMembershipLevel.Admin,
    })

    return (
        <li
            className={clsx(
                'min-h-28 min-w-0 rounded bg-surface-secondary flex flex-col items-center justify-center gap-2 p-1 text-center',
                spansConversion && 'col-span-2'
            )}
            data-attr="email-impact-link-tracking-prompt"
        >
            <span className="font-semibold">Link tracking is off</span>
            <span className="text-xs text-secondary">It connects email clicks to the sessions they start.</span>
            <LemonButton
                type="primary"
                size="small"
                className="max-w-full [&_.LemonButton\_\_chrome]:flex-wrap [&_.LemonButton\_\_chrome]:justify-center [&_.LemonButton\_\_chrome]:px-1"
                center
                loading={linkTrackingSaveLoading}
                disabledReason={restrictedReason ?? linkTrackingDisabledReason}
                onClick={() => turnOnLinkTracking()}
                data-attr="email-impact-turn-on-link-tracking"
            >
                Turn on for project
            </LemonButton>
        </li>
    )
}
