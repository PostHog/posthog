import { useActions } from 'kea'

import { IconArrowLeft } from '@posthog/icons'
import { Button } from '@posthog/quill-primitives'

import { taskTrackerSceneLogic } from '../../scenes/TaskTracker/taskTrackerSceneLogic'
import { QuillTaskHistoryList } from './QuillTaskHistoryList'

export function QuillTaskHistoryPanel(): JSX.Element {
    const { toggleHistory } = useActions(taskTrackerSceneLogic)

    return (
        <div className="flex h-full min-h-0 flex-col">
            <div className="flex shrink-0 items-center border-b border-border px-2 py-1">
                <Button onClick={() => toggleHistory()} data-attr="task-history-back">
                    <IconArrowLeft />
                    Back
                </Button>
            </div>
            <div className="min-h-0 flex-1 overflow-y-auto px-2 py-2">
                <QuillTaskHistoryList />
            </div>
        </div>
    )
}
