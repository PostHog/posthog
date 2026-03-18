import { useActions, useValues } from 'kea'

import { LemonButton, LemonModal, LemonTextArea } from '@posthog/lemon-ui'

import { taskTrackerSceneLogic } from '../logics/taskTrackerSceneLogic'
import { RepositorySelector } from './RepositorySelector'

interface TaskCreateModalProps {
    isOpen: boolean
    onClose: () => void
}

export function TaskCreateModal({ isOpen, onClose }: TaskCreateModalProps): JSX.Element {
    const { submitNewTask, resetNewTaskData, setNewTaskData } = useActions(taskTrackerSceneLogic)
    const { newTaskData, isSubmittingTask } = useValues(taskTrackerSceneLogic)

    const handleCancel = (): void => {
        resetNewTaskData()
        onClose()
    }

    return (
        <LemonModal
            isOpen={isOpen}
            onClose={handleCancel}
            title="Create new task"
            width={800}
            footer={
                <div className="flex gap-2">
                    <LemonButton type="secondary" onClick={handleCancel}>
                        Cancel
                    </LemonButton>
                    <LemonButton type="primary" onClick={submitNewTask} loading={isSubmittingTask}>
                        Create task
                    </LemonButton>
                </div>
            }
        >
            <div className="space-y-6">
                <div>
                    <label className="block text-sm font-medium mb-2">Description</label>
                    <LemonTextArea
                        value={newTaskData.description}
                        onChange={(value) => setNewTaskData({ description: value })}
                        placeholder="Describe the task in detail..."
                        rows={6}
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
        </LemonModal>
    )
}
