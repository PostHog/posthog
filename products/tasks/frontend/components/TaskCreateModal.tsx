import { useActions } from 'kea'
import { useState } from 'react'

import { LemonButton, LemonInput, LemonModal, LemonSelect, LemonTextArea } from '@posthog/lemon-ui'

import { ORIGIN_PRODUCT_LABELS } from '../constants'
import { tasksLogic } from '../tasksLogic'
import { OriginProduct, TaskStatus, TaskUpsertProps } from '../types'
import { RepositoryConfig, RepositorySelector } from './RepositorySelector'

interface TaskCreateModalProps {
    isOpen: boolean
    onClose: () => void
}

interface TaskFormData {
    title: string
    description: string
    status: TaskStatus
    origin_product: OriginProduct
    repositoryConfig: RepositoryConfig
}

export function TaskCreateModal({ isOpen, onClose }: TaskCreateModalProps): JSX.Element {
    const { createTask } = useActions(tasksLogic)

    const [formData, setFormData] = useState<TaskFormData>({
        title: '',
        description: '',
        status: TaskStatus.BACKLOG,
        origin_product: OriginProduct.USER_CREATED,
        repositoryConfig: {
            integrationId: undefined,
            organization: undefined,
            repository: undefined,
        },
    })

    const [loading, setLoading] = useState(false)
    const [errors, setErrors] = useState<Record<string, string>>({})

    const resetForm = (): void => {
        setFormData({
            title: '',
            description: '',
            status: TaskStatus.BACKLOG,
            origin_product: OriginProduct.USER_CREATED,
            repositoryConfig: {
                integrationId: undefined,
                organization: undefined,
                repository: undefined,
            },
        })
    }

    const handleSubmit = async (): Promise<void> => {
        // Validate form
        const newErrors: Record<string, string> = {}

        if (!formData.title.trim()) {
            newErrors.title = 'Title is required'
        }

        if (!formData.description.trim()) {
            newErrors.description = 'Description is required'
        }

        // Validate repository configuration (optional, but if provided, must be complete)
        if (
            formData.repositoryConfig.integrationId ||
            formData.repositoryConfig.organization ||
            formData.repositoryConfig.repository
        ) {
            if (
                !formData.repositoryConfig.integrationId ||
                !formData.repositoryConfig.organization ||
                !formData.repositoryConfig.repository
            ) {
                newErrors.repository = 'Please complete the repository configuration or leave it empty'
            }
        }

        if (Object.keys(newErrors).length > 0) {
            setErrors(newErrors)
            return
        }

        setLoading(true)
        setErrors({})

        try {
            // Convert repository config to API format
            const taskData: TaskUpsertProps = {
                title: formData.title,
                description: formData.description,
                status: formData.status,
                origin_product: formData.origin_product,
                repository_config: {
                    organization: formData.repositoryConfig.organization || '',
                    repository: formData.repositoryConfig.repository || '',
                },
            }

            if (formData.repositoryConfig.integrationId) {
                taskData.github_integration = formData.repositoryConfig.integrationId
            }

            await createTask(taskData)

            resetForm()
            onClose()
        } catch (error) {
            console.error('Failed to create task:', error)
            setErrors({ submit: 'Failed to create task. Please try again.' })
        } finally {
            setLoading(false)
        }
    }

    const handleCancel = (): void => {
        // Reset form and close
        resetForm()
        setErrors({})
        onClose()
    }

    return (
        <LemonModal
            isOpen={isOpen}
            onClose={handleCancel}
            title="Create New Task"
            width={800}
            footer={
                <div className="flex gap-2">
                    <LemonButton type="secondary" onClick={handleCancel}>
                        Cancel
                    </LemonButton>
                    <LemonButton type="primary" onClick={handleSubmit} loading={loading} disabled={loading}>
                        Create Task
                    </LemonButton>
                </div>
            }
        >
            <div className="space-y-6">
                {errors.submit && (
                    <div className="bg-danger-3000 text-danger border border-danger rounded p-3 text-sm">
                        {errors.submit}
                    </div>
                )}

                {/* Basic Information */}
                <div className="space-y-4">
                    <div>
                        <label className="block text-sm font-medium mb-2">Title *</label>
                        <LemonInput
                            value={formData.title}
                            onChange={(value) => setFormData({ ...formData, title: value })}
                            placeholder="Enter task title..."
                            status={errors.title ? 'danger' : undefined}
                        />
                        {errors.title && <p className="text-danger text-xs mt-1">{errors.title}</p>}
                    </div>

                    <div>
                        <label className="block text-sm font-medium mb-2">Description *</label>
                        <LemonTextArea
                            value={formData.description}
                            onChange={(value) => setFormData({ ...formData, description: value })}
                            placeholder="Describe the task in detail..."
                            rows={4}
                        />
                        {errors.description && <p className="text-danger text-xs mt-1">{errors.description}</p>}
                    </div>

                    <div className="grid grid-cols-2 gap-4">
                        <div>
                            <label className="block text-sm font-medium mb-2">Status</label>
                            <LemonSelect
                                value={formData.status}
                                onChange={(value) => setFormData({ ...formData, status: value })}
                                options={[
                                    { value: TaskStatus.BACKLOG, label: 'Backlog' },
                                    { value: TaskStatus.TODO, label: 'To Do' },
                                    { value: TaskStatus.IN_PROGRESS, label: 'In Progress' },
                                    { value: TaskStatus.TESTING, label: 'Testing' },
                                    { value: TaskStatus.DONE, label: 'Done' },
                                ]}
                            />
                        </div>

                        <div>
                            <label className="block text-sm font-medium mb-2">Origin</label>
                            <LemonSelect
                                value={formData.origin_product}
                                onChange={(value) => setFormData({ ...formData, origin_product: value })}
                                options={Object.entries(ORIGIN_PRODUCT_LABELS).map(([key, label]) => ({
                                    value: key as OriginProduct,
                                    label,
                                }))}
                            />
                        </div>
                    </div>
                </div>

                {/* Repository Configuration */}
                <div>
                    <h3 className="text-lg font-medium mb-4">Repository Configuration</h3>
                    <RepositorySelector
                        value={formData.repositoryConfig}
                        onChange={(config) => setFormData({ ...formData, repositoryConfig: config })}
                    />
                    {errors.repository && <p className="text-danger text-xs mt-2">{errors.repository}</p>}
                </div>
            </div>
        </LemonModal>
    )
}
