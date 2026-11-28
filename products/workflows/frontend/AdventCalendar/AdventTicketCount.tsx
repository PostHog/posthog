import { useValues } from 'kea'

import { adventCalendarLogic } from './adventCalendarLogic'
import { AdventTicketIcon } from './AdventTicketIcon'
import { adventTicketsLabel } from './adventTickets'

export function AdventTicketCount(): JSX.Element | null {
    const { ticketsShown } = useValues(adventCalendarLogic)
    if (ticketsShown === null) {
        return null
    }
    return (
        <span className="AdventTicketCount" data-attr="advent-ticket-count">
            <AdventTicketIcon className="h-3 w-5" />
            <span>{adventTicketsLabel(ticketsShown)}</span>
        </span>
    )
}
