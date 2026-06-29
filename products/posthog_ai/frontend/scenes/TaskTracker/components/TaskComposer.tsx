import { useActions, useValues } from 'kea'

import { Composer } from 'products/posthog_ai/frontend/api/primitives'

import { taskTrackerSceneLogic } from '../taskTrackerSceneLogic'
import { RepositorySelector } from './RepositorySelector'

export function TaskComposer(): JSX.Element {
    const { submitNewTask, setNewTaskData } = useActions(taskTrackerSceneLogic)
    const { newTaskData, isSubmittingTask } = useValues(taskTrackerSceneLogic)

    const { integrationId, repository } = newTaskData.repositoryConfig
    const sendDisabledReason = !integrationId
        ? 'Connect a GitHub integration first'
        : !repository
          ? 'Select a repository first'
          : undefined

    return (
        <div className="flex flex-col h-full min-h-0 items-center justify-center overflow-y-auto p-4">
            <div className="w-full max-w-2xl flex flex-col gap-4">
                <h2 className="text-lg font-semibold text-center mb-0">What should the agent do?</h2>

                <Composer.Root
                    value={newTaskData.description}
                    onChange={(value) => setNewTaskData({ description: value })}
                    onSubmit={submitNewTask}
                    loading={isSubmittingTask}
                    disabledReason={sendDisabledReason}
                >
                    <Composer.Frame>
                        <Composer.Field>
                            <Composer.Placeholder>Describe the task in detail…</Composer.Placeholder>
                            <Composer.Textarea submitShortcut="cmd-enter" autoFocus data-attr="task-composer-input" />
                        </Composer.Field>
                        <Composer.Footer>
                            <RepositorySelector
                                value={newTaskData.repositoryConfig}
                                onChange={(config) => setNewTaskData({ repositoryConfig: config })}
                            />
                        </Composer.Footer>
                    </Composer.Frame>
                    <Composer.Submit data-attr="task-composer-send" />
                </Composer.Root>
            </div>
        </div>
    )
}
