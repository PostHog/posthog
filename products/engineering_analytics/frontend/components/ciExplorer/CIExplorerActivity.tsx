import { useValues } from 'kea'

import { IconCommit, IconGitBranch, IconPullRequest, IconXCircle } from '@posthog/icons'

import { dayjs } from 'lib/dayjs'
import { capitalizeFirstLetter } from 'lib/utils/strings'

import { CIActivityEventKind } from '../../lib/ciExplorerActivity'
import { ciExplorerLogic } from '../../scenes/ciExplorerLogic'
import { CIExplorerActivityCommit } from './CIExplorerActivityCommit'

const EVENT: Record<CIActivityEventKind, { text: string; icon: JSX.Element }> = {
    opened: { text: 'opened this pull request', icon: <IconPullRequest /> },
    ready_for_review: { text: 'marked ready for review', icon: <IconPullRequest /> },
    converted_to_draft: { text: 'returned to draft', icon: <IconPullRequest /> },
    merged: { text: 'merged this pull request', icon: <IconPullRequest /> },
    closed: { text: 'closed this pull request', icon: <IconXCircle /> },
}

/** A pull request's activity as a timeline, oldest first and grouped by day. A commit row opens that commit's CI. */
export function CIExplorerActivity(): JSX.Element {
    const { activity } = useValues(ciExplorerLogic)

    if (!activity.length) {
        return (
            <div className="py-16 text-center text-sm text-secondary">
                No activity is synced for this pull request yet. It appears here after the next sync.
            </div>
        )
    }
    return (
        <div className="flex max-w-4xl flex-col gap-6">
            {activity.map((day) => (
                <section key={day.date}>
                    <h2 className="mb-2 ml-[5.25rem] text-xs font-medium text-secondary">
                        {dayjs(day.date).format('MMM D, YYYY')}
                    </h2>
                    {/* The line joins the rows of a day. It sits under the icons, at the middle of their column. */}
                    <ol className="relative m-0 list-none p-0 before:absolute before:bottom-5 before:left-[4.5rem] before:top-5 before:w-px before:bg-border-primary">
                        {day.rows.map((row) => (
                            <li
                                key={`${row.type}:${row.at}:${row.type === 'commit' ? row.headSha : row.kind}`}
                                className="grid min-h-10 grid-cols-[3rem_1.5rem_minmax(0,1fr)] items-center gap-3"
                            >
                                <time
                                    dateTime={row.at}
                                    title={dayjs(row.at).format('MMM D, YYYY HH:mm:ss')}
                                    className="text-right font-mono text-xs text-secondary"
                                >
                                    {dayjs(row.at).format('HH:mm')}
                                </time>
                                <span
                                    className="relative flex justify-center bg-primary py-1 text-base text-secondary"
                                    aria-hidden="true"
                                >
                                    {row.type === 'commit' ? (
                                        row.mergeQueue ? (
                                            <IconGitBranch />
                                        ) : (
                                            <IconCommit />
                                        )
                                    ) : (
                                        EVENT[row.kind].icon
                                    )}
                                </span>
                                {row.type === 'commit' ? (
                                    <CIExplorerActivityCommit commit={row} />
                                ) : (
                                    <span className="px-3 text-sm text-secondary">
                                        {row.actor && <b className="font-medium text-primary">{row.actor} </b>}
                                        {row.actor ? EVENT[row.kind].text : capitalizeFirstLetter(EVENT[row.kind].text)}
                                    </span>
                                )}
                            </li>
                        ))}
                    </ol>
                </section>
            ))}
        </div>
    )
}
