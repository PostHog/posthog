import { useValues } from 'kea'

import { IconPullRequest } from '@posthog/icons'
import { Badge, Card, Text, cn } from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'

import { todaySpacesLogic } from '~/layout/today/todaySpacesLogic'
import { TodayWorkItem, shortTimeAgo } from '~/layout/today/todayWorkItems'

import { TaskUserBasicInfoApi } from '../generated/api.schemas'
import { pullRequestLinkLabel, pullRequestStateMeta } from './TaskPullRequestChip'
import { TaskPullRequest } from './taskPullRequests'
import { TaskUserAvatar, taskUserName } from './TaskUserAvatar'

interface SpaceFeedPullRequestRowProps {
    pullRequest: TaskPullRequest
    /** The session that opened the pull request. */
    session: TodayWorkItem
    author: TaskUserBasicInfoApi | null
}

/** A pull request card in the feed's PRs view, like PostHog Desktop's. It opens on GitHub. */
export function SpaceFeedPullRequestRow({ pullRequest, session, author }: SpaceFeedPullRequestRowProps): JSX.Element {
    const { pullRequestStates } = useValues(todaySpacesLogic)
    const state = pullRequestStates[pullRequest.url]
    const known = pullRequestStateMeta(state)
    // GitHub reports no title to the web, so the row names the session that opened the pull request.
    const title = session.title || 'Untitled session'
    const age = session.timestamp ? shortTimeAgo(session.timestamp) : null

    return (
        <Card size="sm" className="relative my-1.5 gap-0 rounded-xl px-4 pt-3.5 pb-3 transition-colors hover:bg-muted">
            <div className="flex min-w-0 items-center gap-3">
                <div className="flex min-w-0 flex-1 items-baseline gap-1.5">
                    <IconPullRequest
                        className={cn(
                            'size-3.5 shrink-0 translate-y-0.5',
                            known ? known.iconClassName : 'text-muted-foreground'
                        )}
                    />
                    <Text render={<span />} size="xs" variant="muted" className="shrink-0">
                        {`#${pullRequest.number}`}
                    </Text>
                    <LinkPrimitive
                        to={pullRequest.url}
                        target="_blank"
                        aria-label={pullRequestLinkLabel(pullRequest, state)}
                        className="min-w-0 truncate text-sm leading-snug font-semibold text-foreground after:absolute after:inset-0 hover:underline"
                        data-attr="today-space-feed-pr"
                    >
                        {title}
                    </LinkPrimitive>
                    {age && (
                        <Text render={<span />} size="xs" variant="muted" className="shrink-0" translate="no">
                            {`· ${age}`}
                        </Text>
                    )}
                </div>
                {known && <Badge className="shrink-0">{known.label}</Badge>}
            </div>
            <Text size="xs" variant="muted" className="mt-1.5 truncate">
                {pullRequest.repository}
            </Text>
            {author && (
                <div className="mt-3 flex justify-end">
                    <span role="img" aria-label={taskUserName(author)} className="relative flex shrink-0">
                        <TaskUserAvatar user={author} />
                    </span>
                </div>
            )}
        </Card>
    )
}
