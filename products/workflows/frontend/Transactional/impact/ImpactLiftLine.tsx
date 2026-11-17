import { useValues } from 'kea'

import { Tooltip } from '@posthog/lemon-ui'

import { percentage } from 'lib/utils/numbers'

import { emailImpactLogic } from './emailImpactLogic'

export function ImpactLiftLine(): JSX.Element | null {
    const { event, lift, impact, tracked } = useValues(emailImpactLogic)
    if (!event || !lift || !impact) {
        return null
    }
    const days = impact.window_days

    if (!tracked) {
        return lift.notClicked === null ? null : (
            <p className="text-sm m-0">
                <strong>{percentage(lift.notClicked, 1)}</strong> of recipients did <strong>{event}</strong> within{' '}
                {days} days of the send. Without click tracking, PostHog can't tell whether the email led there.
            </p>
        )
    }
    if (lift.clicked === null) {
        return lift.notClicked === null ? null : (
            <p className="text-sm m-0">
                Nobody clicked in this period. <strong>{percentage(lift.notClicked, 1)}</strong> of recipients did{' '}
                <strong>{event}</strong> within {days} days of the send.
            </p>
        )
    }
    return (
        <p className="text-sm m-0">
            <strong>{percentage(lift.clicked, 1)}</strong> of recipients who clicked did <strong>{event}</strong> within{' '}
            {days} days
            {lift.notClicked !== null && (
                <>
                    , against <strong>{percentage(lift.notClicked, 1)}</strong> of recipients who didn't click
                </>
            )}
            .{' '}
            <Tooltip title="People who click are often more likely to convert anyway, so the email may not be what caused it. Recipients who didn't click count from the send.">
                <span className="text-secondary underline decoration-dotted cursor-help">How to read this</span>
            </Tooltip>
        </p>
    )
}
