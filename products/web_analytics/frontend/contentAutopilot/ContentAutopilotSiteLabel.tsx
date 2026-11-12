import { useState } from 'react'

import { LemonTag } from '@posthog/lemon-ui'

import { faviconUrl } from 'scenes/web-analytics/common'

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
        <span className="flex items-center gap-2 min-w-0">
            {faviconFailed ? (
                <span className="size-4 shrink-0 rounded-sm bg-fill-secondary" aria-hidden />
            ) : (
                <img
                    src={faviconUrl(domain)}
                    alt=""
                    className="size-4 shrink-0 rounded-sm"
                    loading="lazy"
                    onError={() => setFaviconFailed(true)}
                />
            )}
            <span className="min-w-0 truncate font-semibold">{children ?? domain}</span>
            {isTarget ? (
                <LemonTag type="success" size="small">
                    Your site
                </LemonTag>
            ) : isCompetitor ? (
                <LemonTag type="warning" size="small">
                    Competitor
                </LemonTag>
            ) : null}
        </span>
    )
}
