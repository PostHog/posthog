import { useActions } from 'kea'

import { Button, cn } from '@posthog/quill'

import { type CitationsLookup, contentAutopilotCitationsModalLogic } from './contentAutopilotCitationsModalLogic'

/** A cited page, cited site or engine search that opens the answers behind it. */
export const ContentAutopilotCitationsLink = ({
    lookup,
    source,
    className,
    title,
    children,
}: {
    lookup: CitationsLookup
    /** Where the link sits, sent with the analytics event. */
    source: string
    className?: string
    title?: string
    children: React.ReactNode
}): JSX.Element => {
    const { openCitations } = useActions(contentAutopilotCitationsModalLogic)
    return (
        <Button
            variant="link-foreground"
            size="sm"
            left
            onClick={() => openCitations(lookup, source)}
            className={cn('max-w-full min-w-0 shrink', className)}
            title={title ?? (typeof children === 'string' ? children : undefined)}
            data-attr="content-autopilot-citations-open"
        >
            <span className="truncate">{children}</span>
        </Button>
    )
}
