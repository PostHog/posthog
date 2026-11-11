import { IconPullRequest } from '@posthog/icons'
import { Badge, Tooltip, TooltipContent, TooltipTrigger, cn } from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'

import { PrStateEnumApi } from '../generated/api.schemas'
import { TaskPullRequest } from './taskPullRequests'

export interface PullRequestStateMeta {
    label: string
    iconClassName: string
}

// The icon carries the state, like PostHog Desktop: the chip itself stays neutral.
const PR_STATES: Record<Exclude<PrStateEnumApi, 'unknown'>, PullRequestStateMeta> = {
    open: { label: 'Open', iconClassName: 'text-success-foreground' },
    draft: { label: 'Draft', iconClassName: 'text-muted-foreground' },
    merged: { label: 'Merged', iconClassName: 'text-completed-foreground' },
    closed: { label: 'Closed', iconClassName: 'text-destructive-foreground' },
}

/** The label and icon color of a known state, or null while GitHub has not reported one. */
export function pullRequestStateMeta(state: PrStateEnumApi | null | undefined): PullRequestStateMeta | null {
    return state && state !== 'unknown' ? PR_STATES[state] : null
}

export function pullRequestLinkLabel(pullRequest: TaskPullRequest, state: PrStateEnumApi | null | undefined): string {
    const known = pullRequestStateMeta(state)
    const name = `pull request ${pullRequest.repository}#${pullRequest.number}`
    return known ? `Open ${known.label.toLowerCase()} ${name} on GitHub` : `Open ${name} on GitHub`
}

/**
 * A chip in the feed card footer, like PostHog Desktop's. `relative` lifts it above the card's full-card link.
 * Regular weight, because RoundHog's medium "4" leaves a gap after it that reads as "#4 21".
 */
export const TASK_CHIP_CLASS = 'relative h-6 max-w-full shrink-0 gap-1.5 rounded-md px-2 text-xs font-normal'

interface TaskPullRequestChipProps {
    pullRequest: TaskPullRequest
    label: string
    dataAttr: string
    state?: PrStateEnumApi | null
}

export function TaskPullRequestChip({ pullRequest, label, dataAttr, state }: TaskPullRequestChipProps): JSX.Element {
    const known = pullRequestStateMeta(state)
    return (
        <Tooltip>
            <TooltipTrigger
                render={
                    <Badge
                        render={<LinkPrimitive to={pullRequest.url} target="_blank" />}
                        aria-label={pullRequestLinkLabel(pullRequest, state)}
                        data-attr={dataAttr}
                        className={cn(
                            TASK_CHIP_CLASS,
                            'border-border bg-fill-hover text-muted-foreground hover:bg-fill-selected hover:text-foreground'
                        )}
                    />
                }
            >
                <IconPullRequest className={cn('size-3 shrink-0', known?.iconClassName)} />
                <span className="min-w-0 truncate">{label}</span>
            </TooltipTrigger>
            <TooltipContent>{known ? `${known.label} · ${pullRequest.url}` : pullRequest.url}</TooltipContent>
        </Tooltip>
    )
}
