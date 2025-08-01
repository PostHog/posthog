import { useState } from 'react'
import { LemonModal, LemonButton, LemonInput, LemonTextArea, LemonSelect } from '@posthog/lemon-ui'
import { useActions } from 'kea'
import { issueTrackerLogic } from '../IssueTrackerLogic'
import { IssueStatus, OriginProduct } from '../types'
import { ORIGIN_PRODUCT_LABELS } from '../constants'
import { RepositorySelector, RepositoryConfig } from './RepositorySelector'

interface IssueCreateModalProps {
    isOpen: boolean
    onClose: () => void
    teamId: number
}

interface IssueFormData {
    title: string
    description: string
    status: IssueStatus
    origin_product: OriginProduct
    repositoryConfig: RepositoryConfig
}

export function IssueCreateModal({ isOpen, onClose }: IssueCreateModalProps): JSX.Element {
    const { createIssue } = useActions(issueTrackerLogic)
    
    const [formData, setFormData] = useState<IssueFormData>({
        title: '',
        description: '',
        status: IssueStatus.BACKLOG,
        origin_product: OriginProduct.USER_CREATED,
        repositoryConfig: {
            integrationId: undefined,
            organization: undefined,
            repository: undefined
        }
    })
    
    const [loading, setLoading] = useState(false)
    const [errors, setErrors] = useState<Record<string, string>>({})

    const handleSubmit = async () => {
        // Validate form
        const newErrors: Record<string, string> = {}
        
        if (!formData.title.trim()) {
            newErrors.title = 'Title is required'
        }
        
        if (!formData.description.trim()) {
            newErrors.description = 'Description is required'
        }
        
        // Validate repository configuration (optional, but if provided, must be complete)
        if (formData.repositoryConfig.integrationId || formData.repositoryConfig.organization || formData.repositoryConfig.repository) {
            if (!formData.repositoryConfig.integrationId || !formData.repositoryConfig.organization || !formData.repositoryConfig.repository) {
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
            const issueData = {
                title: formData.title,
                description: formData.description,
                status: formData.status,
                origin_product: formData.origin_product,
                github_integration: formData.repositoryConfig.integrationId || null,
                repository_config: {
                    organization: formData.repositoryConfig.organization || '',
                    repository: formData.repositoryConfig.repository || ''
                }
            }
            
            await createIssue(issueData)
            
            // Reset form and close modal
            setFormData({
                title: '',
                description: '',
                status: IssueStatus.BACKLOG,
                origin_product: OriginProduct.USER_CREATED,
                repositoryConfig: {
                    integrationId: undefined,
                    organization: undefined,
                    repository: undefined
                }
            })
            
            onClose()
        } catch (error) {
            console.error('Failed to create issue:', error)
            setErrors({ submit: 'Failed to create issue. Please try again.' })
        } finally {
            setLoading(false)
        }
    }

    const handleCancel = () => {
        // Reset form and close
        setFormData({
            title: '',
            description: '',
            status: IssueStatus.BACKLOG,
            origin_product: OriginProduct.USER_CREATED,
            repositoryConfig: {
                integrationId: undefined,
                organization: undefined,
                repository: undefined
            }
        })
        setErrors({})
        onClose()
    }

    return (
        <LemonModal 
            isOpen={isOpen} 
            onClose={handleCancel} 
            title="Create New Issue" 
            width={800}
            footer={
                <div className="flex gap-2">
                    <LemonButton type="secondary" onClick={handleCancel}>
                        Cancel
                    </LemonButton>
                    <LemonButton 
                        type="primary" 
                        onClick={handleSubmit}
                        loading={loading}
                        disabled={loading}
                    >
                        Create Issue
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
                            placeholder="Enter issue title..."
                            status={errors.title ? 'danger' : undefined}
                        />
                        {errors.title && <p className="text-danger text-xs mt-1">{errors.title}</p>}
                    </div>

                    <div>
                        <label className="block text-sm font-medium mb-2">Description *</label>
                        <LemonTextArea
                            value={formData.description}
                            onChange={(value) => setFormData({ ...formData, description: value })}
                            placeholder="Describe the issue in detail..."
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
                                    { value: IssueStatus.BACKLOG, label: 'Backlog' },
                                    { value: IssueStatus.TODO, label: 'To Do' },
                                    { value: IssueStatus.IN_PROGRESS, label: 'In Progress' },
                                    { value: IssueStatus.TESTING, label: 'Testing' },
                                    { value: IssueStatus.DONE, label: 'Done' }
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
                                    label
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