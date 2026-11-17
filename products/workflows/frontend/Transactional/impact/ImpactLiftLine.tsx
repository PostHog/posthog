import { useValues } from 'kea'

import { Tooltip } from '@posthog/lemon-ui'

import { percentage } from 'lib/utils/numbers'

import { emailImpactLogic } from './emailImpactLogic'

export function ImpactLiftLine(): JSX.Element | null {
    const { event, lift, impact, tracked, followedNote } = useValues(emailImpactLogic)
    if (!event || !lift || !impact) {
        return null
    }
    const days = impact.window_days

    if (!tracked) {
        return lift.notClicked === null ? null : (
            <p className="text-sm m-0">
                <strong>{percentage(lift.notClicked, 1)}</strong> of delivered sends were followed by{' '}
                <strong>{event}</strong> within <span>{days}</span> days of the send. Without click tracking, PostHog
                can't tell whether the email led there.
                {followedNote && <span className="text-secondary"> {followedNote}</span>}
            </p>
        )
    }
    if (lift.clicked === null) {
        return lift.notClicked === null ? null : (
            <p className="text-sm m-0">
                <span>
                    {impact.clicked === 0
                        ? 'Nobody clicked in this period.'
                        : "None of the clicks name a person, so PostHog can't follow them."}
                </span>{' '}
                <strong>{percentage(lift.notClicked, 1)}</strong> of sends nobody clicked were followed by{' '}
                <strong>{event}</strong> within <span>{days}</span> days of the send.
                {followedNote && <span className="text-secondary"> {followedNote}</span>}
            </p>
        )
    }
    return (
        <p className="text-sm m-0">
            <strong>{percentage(lift.clicked, 1)}</strong> of clicked sends were followed by <strong>{event}</strong>{' '}
            within <span>{days}</span> days of the click
            {lift.notClicked !== null && (
                <span>
                    , against <strong>{percentage(lift.notClicked, 1)}</strong> of sends nobody clicked
                </span>
            )}
            .{' '}
            <Tooltip title="People who click are often more likely to convert anyway, so the email may not be what caused it. Sends nobody clicked count from the send.">
                <span tabIndex={0} className="text-secondary underline decoration-dotted cursor-help">
                    How to read this
                </span>
            </Tooltip>
            {followedNote && <span className="text-secondary"> {followedNote}</span>}
        </p>
    )
}
