import { useActions, useValues } from 'kea'

import { Button, ButtonGroup, Skeleton, Spinner, Text } from '@posthog/quill-primitives'

import { urls } from 'scenes/urls'

import { taskHistoryLogic } from '../../logics/taskHistoryLogic'
import { compactTimeAgo, isTaskInProgress } from '../../scenes/TaskTracker/components/taskHistoryUtils'
import { taskTrackerSceneLogic } from '../../scenes/TaskTracker/taskTrackerSceneLogic'

export function QuillTaskHistoryPreview(): JSX.Element | null {
    const { history, historyLoading } = useValues(taskHistoryLogic)
    const { toggleHistory, openExistingTask } = useActions(taskTrackerSceneLogic)

    if (!history.length && !historyLoading) {
        return null
    }

    return (
        <div className="flex w-full max-w-120 flex-col gap-1 self-center px-3">
            <div className="flex items-center justify-between gap-2">
                <Text size="xs" weight="medium" variant="muted" render={<h3 className="m-0" />}>
                    Recent tasks
                </Text>
                <Button onClick={() => toggleHistory()} data-attr="task-view-all-history">
                    View all
                </Button>
            </div>
            {historyLoading && !history.length ? (
                <div className="flex flex-col gap-2">
                    <Skeleton className="h-5" />
                    <Skeleton className="h-5" />
                    <Skeleton className="h-5" />
                </div>
            ) : (
                <ButtonGroup orientation="vertical" className="w-full">
                    {history.slice(0, 3).map((task) => (
                        <Button
                            key={task.id}
                            variant="outline"
                            nativeButton={false}
                            // The app's global link color would tint the row, so it keeps the button's text color.
                            className="w-full justify-between gap-2 text-foreground hover:text-foreground"
                            render={
                                // eslint-disable-next-line react/forbid-elements
                                <a
                                    href={urls.taskDetail(task.id)}
                                    onClick={(event) => {
                                        event.preventDefault()
                                        openExistingTask(task)
                                    }}
                                    data-attr="task-open-history-preview"
                                />
                            }
                        >
                            <span className="min-w-0 truncate">{task.title || task.slug}</span>
                            {isTaskInProgress(task) ? (
                                <Spinner aria-label="Working" />
                            ) : (
                                <Text size="xs" variant="muted" render={<span translate="no" />}>
                                    {compactTimeAgo(task.updated_at)}
                                </Text>
                            )}
                        </Button>
                    ))}
                </ButtonGroup>
            )}
        </div>
    )
}
