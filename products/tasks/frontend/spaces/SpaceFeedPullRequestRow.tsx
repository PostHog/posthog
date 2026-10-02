import { useValues } from 'kea'

import { IconPullRequest, type IconProps } from '@posthog/icons'
import { Badge, Card, Text, cn } from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'

import { todaySpacesLogic } from '~/layout/today/todaySpacesLogic'
import { TodayWorkItem, shortTimeAgo } from '~/layout/today/todayWorkItems'

import { TaskUserBasicInfoApi } from '../generated/api.schemas'
import { pullRequestLinkLabel, pullRequestStateMeta } from './TaskPullRequestChip'
import { TaskPullRequest } from './taskPullRequests'
import { TaskUserAvatar, taskUserName } from './TaskUserAvatar'

function IconGitMerge(props: IconProps): JSX.Element {
    return (
        <svg viewBox="0 0 16 16" fill="currentColor" aria-hidden="true" focusable="false" {...props}>
            <path d="M5.45 5.154A4.25 4.25 0 0 0 9.25 7.5h1.378a2.251 2.251 0 1 1 0 1.5H9.25A5.734 5.734 0 0 1 5 7.123v3.505a2.25 2.25 0 1 1-1.5 0V5.372a2.25 2.25 0 1 1 1.95-.218ZM4.25 13.5a.75.75 0 1 0 0-1.5.75.75 0 0 0 0 1.5Zm8.5-4.5a.75.75 0 1 0 0-1.5.75.75 0 0 0 0 1.5ZM5 3.25a.75.75 0 1 0 0 .005V3.25Z" />
        </svg>
    )
}

interface SpaceFeedPullRequestRowProps {
    pullRequest: TaskPullRequest
    pullRequestTitle: string | undefined
    /** The session that opened the pull request. */
    session: TodayWorkItem
    author: TaskUserBasicInfoApi | null
    listRow: boolean
}

/** A pull request in the feed's PRs view, as a card or a list row, like PostHog Desktop's. It opens on GitHub. */
export function SpaceFeedPullRequestRow({
    pullRequest,
    pullRequestTitle,
    session,
    author,
    listRow,
}: SpaceFeedPullRequestRowProps): JSX.Element {
    const { pullRequestStates } = useValues(todaySpacesLogic)
    const state = pullRequestStates[pullRequest.url]
    const known = pullRequestStateMeta(state)
    const title = pullRequestTitle || session.title || 'Untitled session'
    const Icon = state === 'merged' ? IconGitMerge : IconPullRequest
    const icon = <Icon className={cn('size-3.5 shrink-0', known ? known.iconClassName : 'opacity-50')} />
    const number = (
        <Text render={<span />} size="xs" variant="muted" className="shrink-0">
            {`#${pullRequest.number}`}
        </Text>
    )
    const age = session.timestamp ? shortTimeAgo(session.timestamp) : null
    const avatar = author && (
        <span role="img" aria-label={taskUserName(author)} className="relative flex shrink-0">
            <TaskUserAvatar user={author} />
        </span>
    )
    const link = (className: string): JSX.Element => (
        <LinkPrimitive
            to={pullRequest.url}
            target="_blank"
            aria-label={pullRequestLinkLabel(pullRequest, state)}
            className={cn('min-w-0 truncate text-foreground after:absolute after:inset-0', className)}
            data-attr="today-space-feed-pr"
        >
            {title}
        </LinkPrimitive>
    )

    if (listRow) {
        return (
            <div className="relative flex h-8 w-full items-center gap-2 rounded-md px-2 transition-colors hover:bg-fill-selected has-focus-visible:ring-2 has-focus-visible:ring-ring">
                {icon}
                {number}
                {link('flex-1 text-(length:--text-ui) leading-(--text-ui--line-height) font-medium')}
                {avatar}
                {age && (
                    <Text
                        render={<span />}
                        size="xs"
                        variant="muted"
                        className="w-8 shrink-0 text-right"
                        translate="no"
                    >
                        {age}
                    </Text>
                )}
            </div>
        )
    }
    return (
        <Card
            size="sm"
            className="relative my-1.5 gap-0 rounded-xl px-4 pt-3.5 pb-3 transition-colors hover:bg-fill-hover has-focus-visible:ring-2 has-focus-visible:ring-ring"
        >
            <div className="flex min-w-0 items-center gap-3">
                <div className="flex min-w-0 flex-1 items-baseline gap-1.5">
                    <span className="flex translate-y-0.5">{icon}</span>
                    {number}
                    {link('text-sm leading-snug font-semibold')}
                    {age && (
                        <Text render={<span />} size="xs" variant="muted" className="shrink-0" translate="no">
                            {`· ${age}`}
                        </Text>
                    )}
                </div>
                <Badge className="shrink-0">{known?.label ?? 'Open'}</Badge>
                {avatar}
            </div>
            <Text size="xs" variant="muted" className="mt-1.5 truncate">
                {pullRequest.repository}
            </Text>
        </Card>
    )
}
