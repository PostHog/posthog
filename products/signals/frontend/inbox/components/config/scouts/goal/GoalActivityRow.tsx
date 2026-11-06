import { useState } from 'react'

import {
    IconBolt,
    IconCheckCircle,
    IconCode,
    IconFlag,
    IconFlask,
    IconLightBulb,
    IconPause,
    IconPencil,
    IconPiggyBank,
    IconPlay,
    IconPullRequest,
    IconSearch,
    IconTarget,
    IconToggle,
    IconWarning,
} from '@posthog/icons'
import { Link } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { cn } from 'lib/utils/css-classes'
import { urls } from 'scenes/urls'

import type { GoalScoutActivityApi } from 'products/signals/frontend/generated/api.schemas'

import { activitySubject } from '../../../../utils/goal/format'

const LINK_LABELS: Record<string, string> = {
    task: 'Open task',
    experiment: 'Open experiment',
    flag: 'Open feature flag',
    pull_request: 'Open pull request',
}

const TITLE_ICONS: [string, JSX.Element][] = [
    ['Pull request', <IconPullRequest key="pr" />],
    ['Experiment', <IconFlask key="experiment" />],
    ['Feature flag', <IconToggle key="flag" />],
    ['Flag', <IconToggle key="flag-cleanup" />],
    ['Tracking', <IconCode key="tracking" />],
    ['Budget', <IconPiggyBank key="budget" />],
    ['Spend', <IconPiggyBank key="spend" />],
    ['Idea', <IconLightBulb key="idea" />],
    ['Scout run failed', <IconWarning key="failed" />],
    ['Scout', <IconSearch key="scout" />],
    ['Goal reached', <IconTarget key="reached" />],
    ['Goal created', <IconFlag key="created" />],
    ['Goal closed', <IconCheckCircle key="closed" />],
    ['Goal paused', <IconPause key="paused" />],
    ['Goal running', <IconPlay key="running" />],
    ['Goal resumed', <IconPlay key="resumed" />],
    ['Goal', <IconPencil key="goal" />],
    ['Build', <IconCode key="build" />],
]

function entryIcon(entry: GoalScoutActivityApi): JSX.Element {
    return TITLE_ICONS.find(([prefix]) => entry.title.startsWith(prefix))?.[1] ?? <IconBolt />
}

function entryHref(entry: GoalScoutActivityApi): string | null {
    if (!entry.resource_id) {
        return null
    }
    switch (entry.resource) {
        case 'task':
            return urls.taskDetail(entry.resource_id)
        case 'experiment':
            return urls.experiment(Number(entry.resource_id))
        case 'flag':
            return urls.featureFlag(Number(entry.resource_id))
        case 'pull_request':
            return entry.resource_id
        default:
            return null
    }
}

function ActivityIcon({ entry }: { entry: GoalScoutActivityApi }): JSX.Element {
    return <span className="flex shrink-0 text-tertiary [&_svg]:size-3.5">{entryIcon(entry)}</span>
}

export function GoalActivityRow({ group }: { group: GoalScoutActivityApi[] }): JSX.Element {
    const [open, setOpen] = useState(false)
    const [entry] = group
    const notes = [
        ...new Set(group.map((item) => item.detail.slice(activitySubject(item.detail).length).replace(/^\.\s*/, ''))),
    ].filter(Boolean)
    const linked = group
        .map((item) => ({ item, href: entryHref(item) }))
        .filter(
            ({ item, href }, index, all) =>
                !!href && all.findIndex((link) => link.href && link.item.resource === item.resource) === index
        )
    return (
        <li className={cn('flex min-w-0 flex-col rounded', open && 'bg-fill-highlight-50')}>
            <button
                type="button"
                className="flex w-full min-w-0 cursor-pointer items-center gap-2 rounded border-0 bg-transparent px-1 py-1 text-left text-xs text-inherit hover:bg-fill-highlight-50"
                aria-expanded={open}
                onClick={() => setOpen(!open)}
                data-attr="goal-activity-toggle"
            >
                <ActivityIcon entry={entry} />
                <span className="min-w-0 flex-1 truncate">
                    <span className="text-primary">{entry.title}</span>
                    {entry.detail && !open && <span className="text-tertiary"> · {activitySubject(entry.detail)}</span>}
                </span>
                <span className="shrink-0 text-tertiary tabular-nums" translate="no">
                    <TZLabel time={entry.at} showPopover={false} noStyles />
                </span>
            </button>
            {open && (
                <div className="flex flex-col gap-2 px-1 pt-1 pb-2 ps-6.5 text-xs">
                    {entry.detail && <span className="text-primary">{activitySubject(entry.detail)}</span>}
                    {notes.map((note) => (
                        <span key={note} className="text-secondary">
                            {note}
                        </span>
                    ))}
                    {group.length > 1 && (
                        <ol className="m-0 flex list-none flex-col gap-1 p-0">
                            {group.map((item) => (
                                <li key={item.id} className="flex items-center gap-2 text-secondary">
                                    <ActivityIcon entry={item} />
                                    <span className="min-w-0 flex-1 truncate">{item.title}</span>
                                    <span className="shrink-0 text-tertiary tabular-nums">
                                        <TZLabel time={item.at} formatDate="MMM D" formatTime="HH:mm" noStyles />
                                    </span>
                                </li>
                            ))}
                        </ol>
                    )}
                    {(group.length === 1 || linked.length > 0) && (
                        <span className="flex flex-wrap items-center gap-x-3 gap-y-1">
                            {group.length === 1 && (
                                <span className="text-tertiary tabular-nums">
                                    <TZLabel time={entry.at} formatDate="MMM D" formatTime="HH:mm" noStyles />
                                </span>
                            )}
                            {linked.map(({ item, href }) => (
                                <Link
                                    key={item.id}
                                    to={href ?? undefined}
                                    target={item.resource === 'pull_request' ? '_blank' : undefined}
                                    data-attr="goal-activity-open"
                                >
                                    {LINK_LABELS[item.resource] ?? 'Open'}
                                </Link>
                            ))}
                        </span>
                    )}
                </div>
            )}
        </li>
    )
}
