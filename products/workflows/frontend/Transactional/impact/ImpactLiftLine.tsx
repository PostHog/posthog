import { useValues } from 'kea'

import { Tooltip } from '@posthog/lemon-ui'

import { percentage } from 'lib/utils/numbers'

import { emailImpactLogic } from './emailImpactLogic'

interface LiftSentence {
    event: string
    days: number
    note: string | null
}

export function ImpactLiftLine(): JSX.Element | null {
    const { event, lift, impact, followedNote } = useValues(emailImpactLogic)
    if (!event || !lift || !impact) {
        return null
    }
    const sentence = { event, days: impact.window_days, note: followedNote }
    if (lift.clicked !== null) {
        return <ClickedLift {...sentence} clicked={lift.clicked} notClicked={lift.notClicked} />
    }
    if (lift.notClicked !== null) {
        return <NotClickedLift {...sentence} notClicked={lift.notClicked} clicks={impact.clicked} />
    }
    return (
        <p className="text-sm m-0">
            PostHog followed none of the sends in this period to see who did <strong>{event}</strong>.
            <FollowedNote note={followedNote} />
        </p>
    )
}

function ClickedLift({
    event,
    days,
    note,
    clicked,
    notClicked,
}: LiftSentence & { clicked: number; notClicked: number | null }): JSX.Element {
    return (
        <p className="text-sm m-0">
            <strong>{percentage(clicked, 1)}</strong> of clicked sends were followed by <strong>{event}</strong> within{' '}
            <span>{days}</span> days of the click
            {notClicked !== null && (
                <span>
                    , against <strong>{percentage(notClicked, 1)}</strong> of delivered sends with no recorded click
                </span>
            )}
            .{' '}
            <Tooltip title="People who click are often more likely to convert anyway, so the email may not be what caused it. Delivered sends with no recorded click count from the send.">
                <span tabIndex={0} className="text-secondary underline decoration-dotted cursor-help">
                    How to read this
                </span>
            </Tooltip>
            <FollowedNote note={note} />
        </p>
    )
}

function NotClickedLift({
    event,
    days,
    note,
    notClicked,
    clicks,
}: LiftSentence & { notClicked: number; clicks: number }): JSX.Element {
    return (
        <p className="text-sm m-0">
            <NoClickToFollow clicks={clicks} />
            <strong>{percentage(notClicked, 1)}</strong> of delivered sends with no recorded click were followed by{' '}
            <strong>{event}</strong> within <span>{days}</span> days of the send.
            <FollowedNote note={note} />
        </p>
    )
}

function NoClickToFollow({ clicks }: { clicks: number }): JSX.Element {
    return (
        <>
            <span>
                {clicks === 0
                    ? 'No clicks were recorded in this period.'
                    : 'PostHog followed none of the clicked sends.'}
            </span>{' '}
        </>
    )
}

function FollowedNote({ note }: { note: string | null }): JSX.Element | null {
    return note ? <span className="text-secondary"> {note}</span> : null
}
