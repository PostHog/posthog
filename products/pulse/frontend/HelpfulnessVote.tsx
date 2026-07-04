import { useValues } from 'kea'

import { IconThumbsDown, IconThumbsDownFilled, IconThumbsUp, IconThumbsUpFilled } from '@posthog/icons'

import { LemonButton } from 'lib/lemon-ui/LemonButton'

import { pulseLogic } from './pulseLogic'

/** The vote-relevant surface briefs and opportunities share. */
export interface HelpfulnessVoteItem {
    id: string
    my_vote: boolean | null
    helpful_count: number
    not_helpful_count: number
}

export interface HelpfulnessVoteProps {
    item: HelpfulnessVoteItem
    /** Called with the next vote: clicking the current vote clears it (null). */
    onVote: (helpful: boolean | null) => void
    /** Optional leading label, e.g. "Was this helpful?" on the brief detail. */
    label?: string
}

export function HelpfulnessVote({ item, onVote, label }: HelpfulnessVoteProps): JSX.Element {
    const { feedbackVotesInFlight } = useValues(pulseLogic)
    const inFlight = item.id in feedbackVotesInFlight

    return (
        <div className="flex items-center gap-1">
            {label && <span className="text-muted text-sm mr-1">{label}</span>}
            <VoteButton
                helpful={true}
                active={item.my_vote === true}
                count={item.helpful_count}
                inFlight={inFlight}
                onVote={onVote}
            />
            <VoteButton
                helpful={false}
                active={item.my_vote === false}
                count={item.not_helpful_count}
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
