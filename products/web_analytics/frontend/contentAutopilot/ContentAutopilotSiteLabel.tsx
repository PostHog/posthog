import { useState } from 'react'

import { faviconUrl } from 'scenes/web-analytics/common'

import { AiVisibilityTag } from './AiVisibilityTag'

/** A cited site: its favicon, its name (the domain unless `children` replaces it) and whose site it is. */
export const ContentAutopilotSiteLabel = ({
    domain,
    isTarget,
    isCompetitor = false,
    children,
}: {
    domain: string
    isTarget: boolean
    isCompetitor?: boolean
    children?: React.ReactNode
}): JSX.Element => {
    const [faviconFailed, setFaviconFailed] = useState(false)
    return (
        <span className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1">
            <span className="flex min-w-0 max-w-full items-center gap-2">
                {faviconFailed ? (
                    <span className="size-4 shrink-0 rounded-sm bg-muted" aria-hidden />
                ) : (
                    <img
                        src={faviconUrl(domain)}
                        alt=""
                        className="size-4 shrink-0 rounded-sm"
                        loading="lazy"
                        onError={() => setFaviconFailed(true)}
                    />
                )}
                <span className="flex min-w-0 truncate font-semibold">{children ?? domain}</span>
            </span>
            {isTarget ? (
                <AiVisibilityTag type="success" className="shrink-0">
                    Your site
                </AiVisibilityTag>
            ) : isCompetitor ? (
                <AiVisibilityTag type="warning" className="shrink-0">
                    Competitor
                </AiVisibilityTag>
            ) : null}
        </span>
    )
}
