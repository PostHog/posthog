import { useState } from 'react'

import { LemonSkeleton, LemonTag } from '@posthog/lemon-ui'

import { identifierToHuman } from 'lib/utils/strings'

import { ReadonlyRunSurface } from 'products/posthog_ai/frontend/api/readableRun'
import { Task } from 'products/posthog_ai/frontend/types/taskTypes'

import { resolveRunVariant, RunStatusIndicator } from '../cards/runStatusVariant'
import { ActivityDisclosure } from './ActivityDisclosure'
import { taskRunTypeLabel, TaskRunArtefactContent } from './artefactTypes'
import { RunLogContainer } from './RunLogContainer'
import { useArtefactTaskRun } from './useArtefactTaskRun'

/**
 * A `task_run` artefact: the linked task badged from its `(product, type)` (signals-pipeline runs
 * show Research / Implementation / Repo selection; custom agents show their humanized product +
 * type), expanding to the task's run transcript via the shared `ReadonlyRunSurface`. Mirrors desktop
 * `ArtefactTaskRun` (which embeds `TaskLogsPanel`). The task is resolved lazily and the row is
 * disabled until it loads.
 */
export function ArtefactTaskRun({
    content,
    knownTask,
}: {
    content: TaskRunArtefactContent
    /** The resolved task, when the detail logic already fetched it (research/implementation runs) —
     * lets the row skip a redundant `GET /tasks/{id}`. Falls back to a lazy fetch otherwise. */
    knownTask?: Task | null
}): JSX.Element {
    const [expanded, setExpanded] = useState(false)
    const { task, loading, error, status, runId, replayOnly, isCustom } = useArtefactTaskRun(content, knownTask)

    return (
        <ActivityDisclosure
            expanded={expanded}
            onChange={setExpanded}
            disabledReason={
                !task ? (error ? 'Refresh the page to retry loading this task' : 'Task details are loading') : undefined
            }
            fullWidth
            label={
                <span className="flex min-w-0 items-center gap-2">
                    <RunStatusIndicator variant={resolveRunVariant(status)} showLabel={false} />
                    <LemonTag size="small" type="muted">
                        {taskRunTypeLabel(content)}
                    </LemonTag>
                    {isCustom ? (
                        <LemonTag size="small" type="completion">
                            {identifierToHuman(content.product)}
                        </LemonTag>
                    ) : null}
                    {loading ? (
                        <LemonSkeleton className="h-3 w-32" />
                    ) : (
                        <span className={error ? 'truncate text-danger' : 'truncate text-secondary'}>
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
                    <span className="truncate text-secondary">Hide task run</span>
                </span>
            }
        >
            {task && runId ? (
                <RunLogContainer>
                    <ReadonlyRunSurface
                        taskId={task.id}
                        runId={runId}
                        interaction={replayOnly ? 'read-only' : 'live'}
                        threadRowClassName="px-3"
                        threadListClassName="py-3"
                    />
                </RunLogContainer>
            ) : null}
        </ActivityDisclosure>
    )
}
