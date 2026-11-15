import { useActions, useValues } from 'kea'

import { IconPlay } from '@posthog/icons'
import {
    Button,
    Empty,
    EmptyContent,
    EmptyDescription,
    EmptyHeader,
    EmptyMedia,
    EmptyTitle,
} from '@posthog/quill-primitives'

import { isPiTaskRuntime } from '../../../types/taskTypes'
import { taskDetailSceneLogic } from '../taskDetailSceneLogic'

export function QuillTaskNotRunEmpty({ taskId }: { taskId: string }): JSX.Element {
    const { task, runTaskInFlight } = useValues(taskDetailSceneLogic({ taskId }))
    const { runTask } = useActions(taskDetailSceneLogic({ taskId }))
    const canRun = !!task && !isPiTaskRuntime(task.runtime)

    return (
        <Empty data-quill className="flex-1 px-4">
            <EmptyHeader>
                <EmptyMedia variant="icon">
                    <IconPlay />
                </EmptyMedia>
                <EmptyTitle>Not started yet</EmptyTitle>
                {task?.description && <EmptyDescription className="line-clamp-4">{task.description}</EmptyDescription>}
            </EmptyHeader>
            {canRun && (
                <EmptyContent>
                    <Button
                        variant="primary"
                        size="lg"
                        onClick={runTask}
                        loading={runTaskInFlight}
                        className="w-full max-w-60"
                        data-attr="task-empty-run"
                    >
                        <IconPlay />
                        Run task
                    </Button>
                </EmptyContent>
            )}
        </Empty>
    )
}
