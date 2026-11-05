import { useState } from 'react'

import { Badge, Skeleton, cn } from '@posthog/quill'

import { identifierToHuman } from 'lib/utils/strings'

import { ReadonlyRunSurface } from 'products/posthog_ai/frontend/api/readableRun'
import { Task } from 'products/posthog_ai/frontend/types/taskTypes'

import { resolveRunVariant, RunStatusIndicator } from '../cards/runStatusVariant'
import { taskRunTypeLabel, TaskRunArtefactContent } from './artefactTypes'
import { QuillActivityDisclosure } from './QuillActivityDisclosure'
import { QuillRunLogContainer } from './QuillRunLogContainer'
import { useArtefactTaskRun } from './useArtefactTaskRun'

/** The quill sibling of `ArtefactTaskRun`. The row stays disabled until its task loads. */
export function QuillArtefactTaskRun({
    content,
    knownTask,
}: {
    content: TaskRunArtefactContent
    /** The resolved task, when the detail logic already fetched it. Falls back to a lazy fetch otherwise. */
    knownTask?: Task | null
}): JSX.Element {
    const [expanded, setExpanded] = useState(false)
    const { task, loading, error, status, runId, replayOnly, isCustom } = useArtefactTaskRun(content, knownTask)

    return (
        <QuillActivityDisclosure
            expanded={expanded}
            onChange={setExpanded}
            disabledReason={
                !task ? (error ? 'Refresh the page to retry loading this task' : 'Task details are loading') : undefined
            }
            fullWidth
            label={
                <span className="flex min-w-0 items-center gap-2">
                    <RunStatusIndicator variant={resolveRunVariant(status)} showLabel={false} />
                    <Badge>{taskRunTypeLabel(content)}</Badge>
                    {isCustom ? <Badge variant="completed">{identifierToHuman(content.product)}</Badge> : null}
                    {loading ? (
                        <Skeleton className="h-3 w-32" />
                    ) : (
                        <span
                            className={cn('truncate', error ? 'text-destructive-foreground' : 'text-muted-foreground')}
                        >
                            {error
                                ? "Couldn't load this task. Refresh the page to try again."
                                : (task?.title ?? content.task_id)}
                        </span>
                    )}
                </span>
            }
            expandedLabel={
                <span className="flex min-w-0 items-center gap-2">
                    <RunStatusIndicator variant={resolveRunVariant(status)} showLabel={false} />
                    <span className="truncate text-muted-foreground">Hide task run</span>
                </span>
            }
        >
            {task && runId ? (
                <QuillRunLogContainer>
                    <ReadonlyRunSurface
                        taskId={task.id}
                        runId={runId}
                        interaction={replayOnly ? 'read-only' : 'live'}
                        threadRowClassName="px-3"
                        threadListClassName="py-3"
                    />
                </QuillRunLogContainer>
            ) : null}
        </QuillActivityDisclosure>
    )
}
