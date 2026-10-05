import { useActions, useValues } from 'kea'
import { Fragment } from 'react'

import { Link } from '@posthog/lemon-ui'

import { humanFriendlyDuration } from 'lib/utils/durations'

import { ciExplorerLogic } from '../../scenes/ciExplorerLogic'

function Duration({ seconds }: { seconds: number | null }): JSX.Element | null {
    return seconds === null ? null : (
        <span className="font-mono text-xs text-secondary">{humanFriendlyDuration(seconds, { maxUnits: 2 })}</span>
    )
}

/** Where the camera is: the overview, then each node it has zoomed into. The last one carries its duration. */
export function CIExplorerTrail(): JSX.Element {
    const { focusLevels, pushDurationSeconds } = useValues(ciExplorerLogic)
    const { setFocus } = useActions(ciExplorerLogic)
    const last = focusLevels[focusLevels.length - 1]

    return (
        <nav aria-label="Zoom level" className="flex flex-wrap items-baseline gap-x-2 gap-y-1 text-sm">
            {last ? (
                <Link onClick={() => setFocus(null)} subtle data-attr="ci-explorer-trail-overview">
                    Overview
                </Link>
            ) : (
                <>
                    <strong>Overview</strong>
                    <Duration seconds={pushDurationSeconds} />
                </>
            )}
            {focusLevels.map((level) => (
                <Fragment key={level.id}>
                    <span className="text-tertiary" aria-hidden="true">
                        ›
                    </span>
                    {level === last ? (
                        <>
                            <strong>{level.name}</strong>
                            <Duration seconds={level.durationSeconds} />
                        </>
                    ) : (
                        <Link onClick={() => setFocus(level.id)} subtle data-attr="ci-explorer-trail-level">
                            {level.name}
                        </Link>
                    )}
                </Fragment>
            ))}
        </nav>
    )
}
