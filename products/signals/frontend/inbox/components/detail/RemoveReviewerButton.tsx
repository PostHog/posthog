import { useValues } from 'kea'

import { IconX } from '@posthog/icons'
import { LemonButton, LemonMenu } from '@posthog/lemon-ui'

import { userLogic } from 'scenes/userLogic'

import { EnrichedReviewer, ReviewerRemoval } from '../../types'

/**
 * The remove control on a reviewer row. One click on a reason removes the reviewer and records why,
 * so a reason costs no extra step over removing without one. Research and the scouts read the reason
 * when they pick reviewers for later reports.
 */
export function RemoveReviewerButton({
    reviewer,
    displayName,
    disabledReason,
    onRemove,
}: {
    reviewer: EnrichedReviewer
    displayName: string
    disabledReason?: string
    onRemove: (removal?: ReviewerRemoval) => void
}): JSX.Element {
    const { user } = useValues(userLogic)
    const isSelf = !!user?.uuid && (reviewer.user?.uuid ?? reviewer.user_uuid) === user.uuid

    return (
        <LemonMenu
            placement="bottom-end"
            items={[
                {
                    items: [
                        {
                            label: isSelf ? "This isn't my area" : "This isn't their area",
                            onClick: () => onRemove({ reason: 'wrong_area' }),
                        },
                        {
                            label: 'Someone else owns this',
                            onClick: () => onRemove({ reason: 'owned_by_someone_else' }),
                        },
                        {
                            label: isSelf ? "I'm not available" : "They're not available",
                            onClick: () => onRemove({ reason: 'unavailable' }),
                        },
                    ],
                },
                { items: [{ label: 'Just remove', onClick: () => onRemove() }] },
            ]}
        >
            <LemonButton
                type="tertiary"
                size="xsmall"
                icon={<IconX />}
                disabledReason={disabledReason}
                tooltip={`Remove ${displayName}`}
                data-attr="inbox-remove-reviewer"
            />
        </LemonMenu>
    )
}
