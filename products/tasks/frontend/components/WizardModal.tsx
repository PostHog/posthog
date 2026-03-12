import { router } from 'kea-router'
import { useState } from 'react'

import { LemonButton, LemonModal, lemonToast } from '@posthog/lemon-ui'

import api from 'lib/api'

import type { RepositoryConfig } from './RepositorySelector'
import { RepositorySelector } from './RepositorySelector'

interface WizardModalProps {
    isOpen: boolean
    onClose: () => void
}

export function WizardModal({ isOpen, onClose }: WizardModalProps): JSX.Element {
    const [repositoryConfig, setRepositoryConfig] = useState<RepositoryConfig>({
        integrationId: undefined,
        organization: undefined,
        repository: undefined,
    })
    const [isSubmitting, setIsSubmitting] = useState(false)

    const handleCancel = (): void => {
        setRepositoryConfig({
            integrationId: undefined,
            organization: undefined,
            repository: undefined,
        })
        onClose()
    }

    const handleSubmit = async (): Promise<void> => {
        if (!repositoryConfig.organization || !repositoryConfig.repository) {
            lemonToast.error('Please select a repository')
            return
        }

        setIsSubmitting(true)
        try {
            const repository = `${repositoryConfig.organization}/${repositoryConfig.repository}`
            const task = await api.tasks.runWizard({
                repository,
                github_integration: repositoryConfig.integrationId ?? null,
            })
            lemonToast.success('PostHog wizard task started')

            const runId = task.latest_run?.id
            router.actions.push(`/tasks/${task.id}` + (runId ? `?runId=${runId}` : ''))
            handleCancel()
        } catch (e) {
            lemonToast.error(`Failed to start PostHog wizard: ${e instanceof Error ? e.message : 'Unknown error'}`)
        } finally {
            setIsSubmitting(false)
        }
    }

    return (
        <LemonModal
            isOpen={isOpen}
            onClose={handleCancel}
            title="Run PostHog wizard"
            description="Run the PostHog wizard on a repository to set up or update PostHog instrumentation. This will create a pull request with the changes."
            width={640}
            footer={
                <div className="flex gap-2">
                    <LemonButton type="secondary" onClick={handleCancel}>
                        Cancel
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        onClick={handleSubmit}
                        loading={isSubmitting}
                        disabledReason={
                            !repositoryConfig.organization || !repositoryConfig.repository
                                ? 'Select a repository first'
                                : undefined
                        }
                    >
                        Run wizard
                    </LemonButton>
                </div>
            }
        >
            <div>
                <label className="block text-sm font-medium mb-2">Repository</label>
                <RepositorySelector value={repositoryConfig} onChange={setRepositoryConfig} />
            </div>
        </LemonModal>
    )
}
