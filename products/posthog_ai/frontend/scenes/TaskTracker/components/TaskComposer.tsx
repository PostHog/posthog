import { useActions, useValues } from 'kea'

import { IconArrowRight } from '@posthog/icons'
import { LemonButton, LemonTextArea } from '@posthog/lemon-ui'

import { taskTrackerSceneLogic } from '../taskTrackerSceneLogic'
import { RepositorySelector } from './RepositorySelector'

export function TaskComposer(): JSX.Element {
    const { submitNewTask, setNewTaskData } = useActions(taskTrackerSceneLogic)
    const { newTaskData, isSubmittingTask } = useValues(taskTrackerSceneLogic)

    return (
        <div className="flex flex-col h-full min-h-0">
            <div className="flex-1 min-h-0 overflow-y-auto">
                <div className="flex flex-col gap-6 w-full max-w-2xl mx-auto lg:py-8 lg:px-4">
                    <div>
                        <h2 className="text-lg font-semibold mb-1">New task</h2>
                        <p className="text-muted text-sm mb-0">
                            Describe what you'd like an agent to do, then pick a repository to run it against.
                        </p>
                    </div>

                    <div>
                        <label className="block text-sm font-medium mb-2">Description</label>
                        <LemonTextArea
                            value={newTaskData.description}
                            onChange={(value) => setNewTaskData({ description: value })}
                            placeholder="Describe the task in detail..."
                            rows={8}
                            autoFocus
                        />
                    </div>

                    <div>
                        <label className="block text-sm font-medium mb-2">Repository</label>
                        <RepositorySelector
                            value={newTaskData.repositoryConfig}
                            onChange={(config) => setNewTaskData({ repositoryConfig: config })}
                        />
                    </div>
                </div>
            </div>

            <div className="border-t px-4 py-3 shrink-0">
                <div className="w-full max-w-2xl mx-auto flex justify-end">
                    <LemonButton
                        type="primary"
                        icon={<IconArrowRight />}
                        onClick={submitNewTask}
                        loading={isSubmittingTask}
                        disabledReason={!newTaskData.description.trim() ? 'Add a description first' : undefined}
                    >
                        Create task
                    </LemonButton>
                </div>
            </div>
        </div>
    )
}
