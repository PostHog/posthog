import { useState } from 'react'

import { IconCheck } from '@posthog/icons'
import { Link } from '@posthog/lemon-ui'

import { cn } from 'lib/utils/css-classes'

export interface NotificationDestination {
    /** Matches what the saved notification records: a hog function template ID or a subscription target. */
    key: string
    label: string
    icon: JSX.Element
}

/** The question stays collapsed: it's written for the model. */
export function NotificationDetails({
    covers,
    destinations,
    activeDestination,
    prompt,
}: {
    covers: string[]
    destinations: NotificationDestination[]
    activeDestination?: string
    prompt?: string
}): JSX.Element {
    const [promptShown, setPromptShown] = useState(false)

    return (
        <div className="flex flex-col gap-3">
            <div className="flex flex-col gap-1">
                <div className="text-xs font-medium text-muted">What you get</div>
                <ul className="m-0 list-disc pl-4 text-sm">
                    {covers.map((line) => (
                        <li key={line}>{line}</li>
                    ))}
                </ul>
                {prompt && (
                    <>
                        <Link
                            className="text-xs"
                            onClick={() => setPromptShown(!promptShown)}
                            data-attr="mcp-analytics-recurring-report-toggle-prompt"
                        >
                            {promptShown ? 'Hide the question it asks' : 'Show the question it asks'}
                        </Link>
                        {promptShown && <p className="m-0 text-sm text-muted">{prompt}</p>}
                    </>
                )}
            </div>
            <div className="flex flex-col gap-1">
                <div className="text-xs font-medium text-muted">Sender options</div>
                <div className="flex flex-wrap gap-1.5">
                    {destinations.map((destination) => {
                        const active = destination.key === activeDestination
                        return (
                            <span
                                key={destination.key}
                                className={cn(
                                    'flex items-center gap-1.5 rounded border px-1.5 py-0.5 text-xs [&_img]:size-3.5 [&_svg]:size-3.5',
                                    active && 'border-accent bg-accent-highlight-secondary font-medium'
                                )}
                                aria-current={active || undefined}
                            >
                                {destination.icon}
                                {destination.label}
                                {active && <IconCheck className="text-accent" />}
                            </span>
                        )
                    })}
                </div>
            </div>
        </div>
    )
}
