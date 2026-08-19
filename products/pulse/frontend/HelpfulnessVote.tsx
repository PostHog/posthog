import { type FocusEvent, useEffect, useState } from 'react'

import { IconThumbsDown, IconThumbsDownFilled, IconThumbsUp, IconThumbsUpFilled } from '@posthog/icons'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonInput } from 'lib/lemon-ui/LemonInput'

/** The vote-relevant surface briefs and opportunities share. */
export interface HelpfulnessVoteItem {
    id: string
    my_vote: boolean | null
    my_reason: string | null
    helpful_count: number
    not_helpful_count: number
}

export interface HelpfulnessVoteProps {
    item: HelpfulnessVoteItem
    /** Whether this item's vote is mid-flight — owned by the caller's logic (briefs and opportunities
     * live in different logics), so it comes in as a prop rather than being read here. */
    inFlight: boolean
    /** Called with the next vote and the reason to store: clicking the current vote clears it (null). */
    onVote: (helpful: boolean | null, reason: string) => void
    /** Optional leading label, e.g. "Was this helpful?" on the brief detail. */
    label?: string
}

export function HelpfulnessVote({ item, inFlight, onVote, label }: HelpfulnessVoteProps): JSX.Element {
    const [reason, setReason] = useState(item.my_reason ?? '')
    // Keep the input in sync when the stored reason changes (revote, clear, or reload).
    useEffect(() => setReason(item.my_reason ?? ''), [item.my_reason])

    const submitReason = (e?: FocusEvent<HTMLInputElement>): void => {
        // If focus is leaving for a vote button, its click already carries this reason — submitting
        // here too would occupy the in-flight guard and drop that click's vote change.
        const nextAttr = (e?.relatedTarget as HTMLElement | null)?.getAttribute('data-attr') ?? ''
        if (nextAttr === 'pulse-feedback-helpful' || nextAttr === 'pulse-feedback-not-helpful') {
            return
        }
        if (item.my_vote !== null && reason !== (item.my_reason ?? '')) {
            onVote(item.my_vote, reason)
        }
    }

    return (
        <div className="flex flex-col gap-1">
            <div className="flex items-center gap-1">
                {label && <span className="text-muted text-sm mr-1">{label}</span>}
                <VoteButton
                    helpful={true}
                    active={item.my_vote === true}
                    count={item.helpful_count}
                    inFlight={inFlight}
                    onVote={(helpful) => onVote(helpful, reason)}
                />
                <VoteButton
                    helpful={false}
                    active={item.my_vote === false}
                    count={item.not_helpful_count}
                    inFlight={inFlight}
                    onVote={(helpful) => onVote(helpful, reason)}
                />
            </div>
            {item.my_vote !== null && (
                <LemonInput
                    size="small"
                    value={reason}
                    onChange={setReason}
                    onBlur={submitReason}
                    onPressEnter={() => submitReason()}
                    disabled={inFlight}
                    maxLength={1000}
                    placeholder="Add a reason (optional)"
                    data-attr="pulse-feedback-reason"
                />
            )}
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
    const action = active ? 'Clear your vote' : helpful ? 'Helpful' : 'Not helpful'
    // Fold the count into the accessible name — LemonButton derives aria-label from the tooltip
    // string otherwise, which drops the count from what a screen reader announces.
    const ariaLabel = count > 0 ? `${action}, ${count} ${count === 1 ? 'vote' : 'votes'}` : action
    return (
        <LemonButton
            size="small"
            active={active}
            icon={active ? filledIcon : outlineIcon}
            disabledReason={inFlight ? 'Saving your vote…' : undefined}
            tooltip={action}
            aria-label={ariaLabel}
            data-attr={helpful ? 'pulse-feedback-helpful' : 'pulse-feedback-not-helpful'}
            onClick={() => onVote(active ? null : helpful)}
        >
            {count > 0 ? <span className="text-muted text-xs">{count}</span> : undefined}
        </LemonButton>
    )
}
