import clsx from 'clsx'
import { useActions } from 'kea'

import { Link } from '@posthog/lemon-ui'

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
        <Link
            onClick={() => openCitations(lookup, source)}
            className={clsx('min-w-0 text-left', className)}
            title={title}
            data-attr="content-autopilot-citations-open"
        >
            {children}
        </Link>
    )
}
