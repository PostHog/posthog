import { useValues } from 'kea'

import { IconChevronDown } from '@posthog/icons'
import {
    Button,
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuGroup,
    DropdownMenuItem,
    DropdownMenuLabel,
    DropdownMenuSeparator,
    DropdownMenuTrigger,
    Text,
    cn,
} from '@posthog/quill'

import { QuillPersonAvatar } from 'lib/components/QuillPersonAvatar/QuillPersonAvatar'
import { userLogic } from 'scenes/userLogic'

import { EnrichedReviewer, ReviewerRemoval } from '../../types'
import { reviewerRemovalMenu } from './suggestedReviewers'

const NOT_LINKED = 'This reviewer is not linked to a PostHog member and cannot receive the report.'

/**
 * The quill sibling of `ReviewerRowMenu`, for the report page behind `today-rail-nav`. It also draws the
 * reviewer's avatar menu and name, which both quill reviewer rows share.
 */
export function QuillReviewerRowMenu({
    reviewer,
    displayName,
    disabledReason,
    onRemove,
}: {
    reviewer: EnrichedReviewer
    displayName: string
    /** Why the reviewer cannot be removed right now. The menu still opens and explains it. */
    disabledReason?: string
    onRemove: (removal?: ReviewerRemoval) => void
}): JSX.Element {
    const { user } = useValues(userLogic)
    const { title, reasons } = reviewerRemovalMenu(reviewer, displayName, user?.uuid)

    return (
        <div className={cn('flex min-w-0 items-center gap-2', !reviewer.user && 'opacity-75')}>
            <DropdownMenu>
                <DropdownMenuTrigger
                    render={
                        <Button
                            className="shrink-0 gap-1"
                            tooltip={`Actions for ${displayName}`}
                            aria-label={`Actions for ${displayName}`}
                            data-attr="inbox-reviewer-row"
                        />
                    }
                >
                    <QuillPersonAvatar name={displayName} email={reviewer.user?.email} size="xs" />
                    <IconChevronDown />
                </DropdownMenuTrigger>
                <DropdownMenuContent>
                    {!reviewer.user && (
                        <Text size="xs" variant="muted" className="m-0 max-w-64 px-2 py-1.5 whitespace-normal">
                            {NOT_LINKED}
                        </Text>
                    )}
                    <DropdownMenuGroup>
                        <DropdownMenuLabel>{title}</DropdownMenuLabel>
                        {reasons.map((option) => (
                            <DropdownMenuItem
                                key={option.value}
                                disabledReason={disabledReason}
                                onClick={() => onRemove({ reason: option.value })}
                            >
                                {option.label}
                            </DropdownMenuItem>
                        ))}
                    </DropdownMenuGroup>
                    <DropdownMenuSeparator />
                    <DropdownMenuItem disabledReason={disabledReason} onClick={() => onRemove()}>
                        Without a reason
                    </DropdownMenuItem>
                </DropdownMenuContent>
            </DropdownMenu>
            <Text size="xs" className="ph-no-capture min-w-0 truncate" render={<span />}>
                {displayName}
            </Text>
        </div>
    )
}
