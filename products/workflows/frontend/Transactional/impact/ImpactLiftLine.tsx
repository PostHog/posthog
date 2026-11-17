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
    const { event, lift, impact, tracked, followedNote } = useValues(emailImpactLogic)
    if (!event || !lift || !impact) {
        return null
    }
    const sentence = { event, days: impact.window_days, note: followedNote }
    if (lift.clicked !== null && tracked) {
        return <ClickedLift {...sentence} clicked={lift.clicked} notClicked={lift.notClicked} />
    }
    return lift.notClicked === null ? null : (
        <NotClickedLift {...sentence} notClicked={lift.notClicked} tracked={tracked} clicks={impact.clicked} />
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
                    , against <strong>{percentage(notClicked, 1)}</strong> of sends nobody clicked
                </span>
            )}
            .{' '}
            <Tooltip title="People who click are often more likely to convert anyway, so the email may not be what caused it. Sends nobody clicked count from the send.">
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
    tracked,
    clicks,
}: LiftSentence & { notClicked: number; tracked: boolean; clicks: number }): JSX.Element {
    return (
        <p className="text-sm m-0">
            {tracked && <NoClickToFollow clicks={clicks} />}
            <strong>{percentage(notClicked, 1)}</strong> of {tracked ? 'sends nobody clicked' : 'delivered sends'} were
            followed by <strong>{event}</strong> within <span>{days}</span> days of the send.
            {!tracked && " Without click tracking, PostHog can't tell whether the email led there."}
            <FollowedNote note={note} />
        </p>
    )
}

function NoClickToFollow({ clicks }: { clicks: number }): JSX.Element {
    return (
        <>
            <span>
                {clicks === 0
                    ? 'Nobody clicked in this period.'
                    : "None of the clicks name a person, so PostHog can't follow them."}
            </span>{' '}
        </>
    )
}

function FollowedNote({ note }: { note: string | null }): JSX.Element | null {
    return note ? <span className="text-secondary"> {note}</span> : null
}
