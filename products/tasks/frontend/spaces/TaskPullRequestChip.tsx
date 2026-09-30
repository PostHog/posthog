import { IconPullRequest } from '@posthog/icons'
import { Badge, Tooltip, TooltipContent, TooltipTrigger, cn } from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'

import { PrStateEnumApi } from '../generated/api.schemas'
import { TaskPullRequest } from './taskPullRequests'

// The icon carries the state, like PostHog Desktop: the chip itself stays neutral.
const PR_STATES: Record<Exclude<PrStateEnumApi, 'unknown'>, { label: string; iconClassName: string }> = {
    open: { label: 'Open', iconClassName: 'text-success-foreground' },
    draft: { label: 'Draft', iconClassName: 'text-muted-foreground' },
    merged: { label: 'Merged', iconClassName: 'text-completed-foreground' },
    closed: { label: 'Closed', iconClassName: 'text-destructive-foreground' },
}

interface TaskPullRequestChipProps {
    pullRequest: TaskPullRequest
    label: string
    dataAttr: string
    state?: PrStateEnumApi | null
    /** `row` for the compact sidebar pill, `card` for the feed card chip. */
    size?: 'row' | 'card'
}

export function TaskPullRequestChip({
    pullRequest,
    label,
    dataAttr,
    state,
    size = 'card',
}: TaskPullRequestChipProps): JSX.Element {
    const known = state && state !== 'unknown' ? PR_STATES[state] : null
    const name = `pull request ${pullRequest.repository}#${pullRequest.number}`
    return (
        <Tooltip>
            <TooltipTrigger
                render={
                    <Badge
                        render={<LinkPrimitive to={pullRequest.url} target="_blank" />}
                        aria-label={
                            known ? `Open ${known.label.toLowerCase()} ${name} on GitHub` : `Open ${name} on GitHub`
                        }
                        data-attr={dataAttr}
                        // `relative` lifts it above the feed card's full-card link, so it stays clickable.
                        className={cn(
                            'relative max-w-full shrink-0 gap-1 border-border bg-fill-hover text-muted-foreground tabular-nums hover:bg-fill-selected hover:text-foreground',
                            size === 'row' ? 'rounded-sm px-1' : 'h-6 rounded-md px-2 text-xs'
                        )}
                    />
                }
            >
                <IconPullRequest
                    className={cn('shrink-0', size === 'row' ? 'size-2.5' : 'size-3', known?.iconClassName)}
                />
                <span className="min-w-0 truncate">{label}</span>
            </TooltipTrigger>
            <TooltipContent>{known ? `${known.label} · ${pullRequest.url}` : pullRequest.url}</TooltipContent>
        </Tooltip>
    )
}
