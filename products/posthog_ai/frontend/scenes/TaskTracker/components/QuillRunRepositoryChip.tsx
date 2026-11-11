import { IconGithub } from '@posthog/icons'
import { Tooltip, TooltipContent, TooltipTrigger } from '@posthog/quill-primitives'

export interface QuillRunRepositoryChipProps {
    repository: string
    branch?: string | null
}

export function QuillRunRepositoryChip({ repository, branch }: QuillRunRepositoryChipProps): JSX.Element {
    return (
        <Tooltip>
            <TooltipTrigger
                render={
                    <span
                        tabIndex={0}
                        className="inline-flex h-6 max-w-full items-center gap-1.5 rounded-sm border border-border px-2 text-xs"
                        data-attr="task-run-repository-chip"
                    >
                        <IconGithub className="shrink-0" />
                        <span className="max-w-40 truncate font-medium">{repository.split('/').pop()}</span>
                        {branch && <span className="max-w-28 truncate text-muted-foreground">{branch}</span>}
                    </span>
                }
            />
            <TooltipContent>
                {branch ? `This chat works in ${repository} on ${branch}` : `This chat works in ${repository}`}
            </TooltipContent>
        </Tooltip>
    )
}
