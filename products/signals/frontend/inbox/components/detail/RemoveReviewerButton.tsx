import { useValues } from 'kea'

import { IconChevronDown, IconX } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { LemonMenuOverlay } from 'lib/lemon-ui/LemonMenu/LemonMenu'
import { userLogic } from 'scenes/userLogic'

import { EnrichedReviewer, ReviewerRemoval } from '../../types'

/**
 * The remove control on a reviewer row. The X removes the reviewer in one click, as before reasons
 * existed. The arrow next to it removes the reviewer with a reason, which research and the scouts
 * read when they pick reviewers for later reports.
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
        <LemonButton
            type="tertiary"
            size="xsmall"
            icon={<IconX />}
            disabledReason={disabledReason}
            tooltip={`Remove ${displayName}`}
            onClick={() => onRemove()}
            data-attr="inbox-remove-reviewer"
            sideAction={{
                icon: <IconChevronDown />,
                disabledReason,
                tooltip: 'Remove with a reason',
                'aria-label': `Remove ${displayName} with a reason`,
                'data-attr': 'inbox-remove-reviewer-reasons',
                dropdown: {
                    placement: 'bottom-end',
                    overlay: (
                        <LemonMenuOverlay
                            items={[
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
                            ]}
                        />
                    ),
                },
            }}
        />
    )
}
