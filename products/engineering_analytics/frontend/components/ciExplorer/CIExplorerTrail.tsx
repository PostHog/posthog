import { useActions, useValues } from 'kea'
import { Fragment } from 'react'

import { Link, Tooltip } from '@posthog/lemon-ui'

import { humanFriendlyDuration } from 'lib/utils/durations'

import { ciExplorerLogic } from '../../scenes/ciExplorerLogic'

function Elapsed({ seconds, title }: { seconds: number | null; title: string }): JSX.Element | null {
    return seconds === null ? null : (
        <Tooltip title={title}>
            <span className="font-mono text-xs text-secondary">
                {humanFriendlyDuration(seconds, { maxUnits: 2 })} elapsed
            </span>
        </Tooltip>
    )
}

function Separator(): JSX.Element {
    return (
        <span className="text-tertiary" aria-hidden="true">
            ›
        </span>
    )
}

/** Where the camera is: the commit's workflows, then each node it has zoomed into. The last one carries its elapsed time. */
export function CIExplorerTrail(): JSX.Element {
    const { focusLevels, pushDurationSeconds, activePush, onOlderCommit } = useValues(ciExplorerLogic)
    const { setFocus, setView } = useActions(ciExplorerLogic)
    const last = focusLevels[focusLevels.length - 1]
    // An older commit was reached from the activity, so the trail starts there.
    const root = onOlderCommit && activePush ? `Commit ${activePush.headSha.slice(0, 7)}` : 'Workflows'

    return (
        <nav aria-label="Zoom level" className="flex flex-wrap items-baseline gap-x-2 gap-y-1 text-sm">
            {onOlderCommit && (
                <>
                    <Link onClick={() => setView('activity')} subtle data-attr="ci-explorer-trail-activity">
                        Activity
                    </Link>
                    <Separator />
                </>
            )}
            {last ? (
                <Link onClick={() => setFocus(null)} subtle data-attr="ci-explorer-trail-overview">
                    {root}
                </Link>
            ) : (
                <>
                    <strong>{root}</strong>
                    <Elapsed
                        seconds={pushDurationSeconds}
                        title="First workflow start to last workflow finish on this commit"
                    />
                </>
            )}
            {focusLevels.map((level) => (
                <Fragment key={level.id}>
                    <Separator />
                    {level === last ? (
                        <>
                            <strong>{level.name}</strong>
                            <Elapsed seconds={level.durationSeconds} title="First start to last finish" />
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
