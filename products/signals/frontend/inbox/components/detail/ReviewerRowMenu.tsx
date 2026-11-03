import { useValues } from 'kea'
import { ReactNode } from 'react'

import { LemonButton, LemonMenu, LemonMenuItem } from '@posthog/lemon-ui'

import { userLogic } from 'scenes/userLogic'

import { EnrichedReviewer, ReviewerRemoval } from '../../types'
import { reviewerRemovalReasonOptions } from '../../utils/reviewerRemovalReasons'

/**
 * Makes a reviewer's name the trigger for the actions on that reviewer, so the row shows no buttons
 * until someone opens it. Removing with a reason costs no extra step over removing without one, and
 * research and the scouts read the reason when they pick reviewers for later reports.
 */
export function ReviewerRowMenu({
    reviewer,
    displayName,
    disabledReason,
    onRemove,
    children,
}: {
    reviewer: EnrichedReviewer
    displayName: string
    /** Why the reviewer cannot be removed right now. The menu still opens and explains it. */
    disabledReason?: string
    onRemove: (removal?: ReviewerRemoval) => void
    /** The reviewer's name and avatar, rendered as the trigger. */
    children: ReactNode
}): JSX.Element {
    const { user } = useValues(userLogic)
    const isSelf = !!user?.uuid && (reviewer.user?.uuid ?? reviewer.user_uuid) === user.uuid
    const title = isSelf ? 'Remove yourself' : `Remove ${displayName}`
    const reason = (label: string, value: NonNullable<ReviewerRemoval['reason']>): LemonMenuItem => ({
        label,
        disabledReason,
        onClick: () => onRemove({ reason: value }),
    })

    return (
        <LemonMenu
            placement="bottom-start"
            items={[
                {
                    title,
                    items: reviewerRemovalReasonOptions(isSelf).map((option) => reason(option.label, option.value)),
                },
                { items: [{ label: 'Without a reason', disabledReason, onClick: () => onRemove() }] },
            ]}
        >
            <LemonButton
                type="tertiary"
                size="xsmall"
                fullWidth
                // No dropdown arrow: the row shows nothing extra until someone opens it.
                sideIcon={null}
                aria-label={`Actions for ${displayName}`}
                data-attr="inbox-reviewer-row"
            >
                {children}
            </LemonButton>
        </LemonMenu>
    )
}
