import { LemonTag } from '@posthog/lemon-ui'

import { INBOX_PERSONAL_TIERS } from '../../filterOptions'

/** The tier the user's personal ranking gave the report, in the card's meta row on the Personalized sort. */
export function ReportCardPersonalTier({ tier }: { tier: string }): JSX.Element {
    const known = INBOX_PERSONAL_TIERS[tier]
    return (
        <LemonTag size="small" type={known?.tagType ?? 'default'} data-attr="inbox-personal-tier">
            {known?.label ?? tier}
        </LemonTag>
    )
}
