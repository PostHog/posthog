import { useState } from 'react'

import { Text } from '@posthog/quill'

import { faviconUrl } from 'scenes/web-analytics/common'

import { AiVisibilityTag } from './AiVisibilityTag'

/** A cited site: its favicon, its name (the domain unless `children` replaces it) and whose site it is.
 *  A `subtitle`, such as the domain under a brand name, sits under the name, beside the favicon. */
export const ContentAutopilotSiteLabel = ({
    domain,
    isTarget,
    isCompetitor = false,
    subtitle,
    children,
}: {
    domain: string
    isTarget: boolean
    isCompetitor?: boolean
    subtitle?: React.ReactNode
    children?: React.ReactNode
}): JSX.Element => {
    const [faviconFailed, setFaviconFailed] = useState(false)
    const favicon = faviconFailed ? (
        <span className="size-4 shrink-0 rounded-sm bg-muted" aria-hidden />
    ) : (
        <img
            src={faviconUrl(domain)}
            alt=""
            className="size-4 shrink-0 rounded-sm"
            loading="lazy"
            onError={() => setFaviconFailed(true)}
        />
    )
    const tag = isTarget ? (
        <AiVisibilityTag type="success" className="shrink-0">
            Your site
        </AiVisibilityTag>
    ) : isCompetitor ? (
        <AiVisibilityTag type="warning" className="shrink-0">
            Competitor
        </AiVisibilityTag>
    ) : null
    const name = <span className="flex min-w-0 truncate font-semibold">{children ?? domain}</span>

    if (subtitle) {
        return (
            <span className="flex min-w-0 items-center gap-2">
                {favicon}
                <span className="flex min-w-0 flex-col">
                    <span className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1">
                        {name}
                        {tag}
                    </span>
                    <Text size="xs" variant="muted" render={<span className="m-0 truncate" />}>
                        {subtitle}
                    </Text>
                </span>
            </span>
        )
    }
    return (
        <span className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1">
            <span className="flex min-w-0 max-w-full items-center gap-2">
                {favicon}
                {name}
            </span>
            {tag}
        </span>
    )
}
