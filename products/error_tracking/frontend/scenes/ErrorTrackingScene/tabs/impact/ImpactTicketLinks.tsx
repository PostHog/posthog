import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { Button } from 'lib/ui/quill'
import { urls } from 'scenes/urls'

import type { SupportTicketsIssue } from '../recommendations/types'

export function ImpactTicketLinks({ tickets }: { tickets: SupportTicketsIssue['ticket_refs'] }): JSX.Element {
    return (
        <span className="inline-flex flex-wrap gap-x-1">
            {tickets.map((ticket) => (
                <Button
                    key={ticket.id}
                    variant="link"
                    size="xs"
                    nativeButton={false}
                    render={<LinkPrimitive to={urls.supportTicketDetail(ticket.id)} />}
                    data-attr="error-tracking-impact-ticket"
                >
                    {`#${ticket.number}`}
                </Button>
            ))}
        </span>
    )
}
