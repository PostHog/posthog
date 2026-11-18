import { Badge, cn } from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'

import { ArtifactIcon } from 'products/posthog_ai/frontend/api/taskArtifacts'

import { TaskFile } from './taskFiles'
import { TASK_CHIP_CLASS } from './TaskPullRequestChip'

interface TaskFileChipProps {
    taskFile: TaskFile
    onOpen: () => void
}

/** A file the agent handed back. It opens the session's Artifacts tab on that file, like PostHog Desktop. */
export function TaskFileChip({ taskFile, onOpen }: TaskFileChipProps): JSX.Element {
    const { file, url } = taskFile
    return (
        <Badge
            render={<LinkPrimitive to={url} onClick={onOpen} />}
            aria-label={`Open ${file.name}`}
            data-attr="today-file-chip-feed"
            className={cn(
                TASK_CHIP_CLASS,
                'border-border bg-fill-hover text-muted-foreground hover:bg-fill-selected hover:text-foreground'
            )}
        >
            <ArtifactIcon artifact={file.latest} className="size-3 shrink-0" />
            <span className="max-w-40 min-w-0 truncate">{file.name}</span>
        </Badge>
    )
}
