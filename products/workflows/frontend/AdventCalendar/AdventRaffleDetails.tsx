import { useValues } from 'kea'

import { Link } from '@posthog/lemon-ui'

import { adventCalendarLogic } from './adventCalendarLogic'
import { AdventTicketIcon } from './AdventTicketIcon'
import { adventTicketsLabel } from './adventTickets'

const SWEATER_URL = 'https://posthog.com/merch?product=posthog-winter-sweater'

export function AdventRaffleDetails(): JSX.Element {
    const { tickets } = useValues(adventCalendarLogic)
    return (
        <div className="flex flex-col gap-1.5 text-xs leading-snug" data-attr="advent-raffle-details">
            <p className="m-0 font-semibold">Open each door on its day to enter the raffle.</p>
            <p className="m-0">
                Win 1 of 20 $55 merch codes for a{' '}
                <Link to={SWEATER_URL} target="_blank" data-attr="advent-raffle-sweater">
                    Christmas sweater
                </Link>{' '}
                or any merch you like.
            </p>
            {tickets !== null && (
                <p className="m-0 flex items-center gap-1.5 font-semibold" data-attr="advent-raffle-tickets">
                    <AdventTicketIcon className="h-3 w-5 shrink-0" />
                    <span>{`You have ${adventTicketsLabel(tickets)}.`}</span>
                </p>
            )}
            <p className="m-0 text-secondary">
                Free to enter for every PostHog user. Winners are drawn after December 24 and get an email.
            </p>
        </div>
    )
}
