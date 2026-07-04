import { IconThumbsDown, IconThumbsDownFilled, IconThumbsUp, IconThumbsUpFilled } from '@posthog/icons'

import { LemonButton } from 'lib/lemon-ui/LemonButton'

export interface HelpfulnessVoteProps {
    myVote: boolean | null
    helpfulCount: number
    notHelpfulCount: number
    inFlight: boolean
    /** Called with the next vote: clicking the current vote clears it (null). */
    onVote: (helpful: boolean | null) => void
    /** Optional leading label, e.g. "Was this helpful?" on the brief detail. */
    label?: string
}

export function HelpfulnessVote({
    myVote,
    helpfulCount,
    notHelpfulCount,
    inFlight,
    onVote,
    label,
}: HelpfulnessVoteProps): JSX.Element {
    return (
        <div className="flex items-center gap-1">
            {label && <span className="text-muted text-sm mr-1">{label}</span>}
            <VoteButton
                helpful={true}
                active={myVote === true}
                count={helpfulCount}
                inFlight={inFlight}
                onVote={onVote}
            />
            <VoteButton
                helpful={false}
                active={myVote === false}
                count={notHelpfulCount}
                inFlight={inFlight}
                onVote={onVote}
            />
        </div>
    )
}

function VoteButton({
    helpful,
    active,
    count,
    inFlight,
    onVote,
}: {
    helpful: boolean
    active: boolean
    count: number
    inFlight: boolean
    onVote: (helpful: boolean | null) => void
}): JSX.Element {
    const [outlineIcon, filledIcon] = helpful
        ? [<IconThumbsUp key="up" />, <IconThumbsUpFilled key="up-filled" />]
        : [<IconThumbsDown key="down" />, <IconThumbsDownFilled key="down-filled" />]
    return (
        <LemonButton
            size="small"
            active={active}
            icon={active ? filledIcon : outlineIcon}
            disabledReason={inFlight ? 'Saving your vote…' : undefined}
            tooltip={active ? 'Clear your vote' : helpful ? 'Helpful' : 'Not helpful'}
            data-attr={helpful ? 'pulse-feedback-helpful' : 'pulse-feedback-not-helpful'}
            onClick={() => onVote(active ? null : helpful)}
        >
            {count > 0 ? <span className="text-muted text-xs">{count}</span> : undefined}
        </LemonButton>
    )
}
