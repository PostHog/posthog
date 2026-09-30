import { IconPullRequest } from '@posthog/icons'
import { Button, Tooltip, TooltipContent, TooltipTrigger } from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'

import { TaskPullRequest } from './taskPullRequests'

interface TaskPullRequestChipProps {
    pullRequest: TaskPullRequest
    label: string
    dataAttr: string
}

export function TaskPullRequestChip({ pullRequest, label, dataAttr }: TaskPullRequestChipProps): JSX.Element {
    return (
        <Tooltip>
            <TooltipTrigger
                render={
                    <Button
                        size="xs"
                        variant="outline"
                        render={<LinkPrimitive to={pullRequest.url} target="_blank" />}
                        aria-label={`Open pull request ${pullRequest.repository}#${pullRequest.number} on GitHub`}
                        data-attr={dataAttr}
                        // Sits above the card's full-card link, so it stays clickable.
                        className="relative max-w-full shrink-0 tabular-nums"
                    />
                }
            >
                <IconPullRequest className="shrink-0" />
                <span className="min-w-0 truncate">{label}</span>
            </TooltipTrigger>
            <TooltipContent>{pullRequest.url}</TooltipContent>
        </Tooltip>
    )
}
