import React, { useEffect, useState } from 'react'
import { LemonButton, LemonInput, LemonSwitch, LemonCard, LemonTextArea, LemonDivider, LemonLabel } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { IconGithub, IconRefresh } from 'lib/lemon-ui/icons'
import { githubIntegrationLogic, GitHubIntegrationLogicProps } from '../logic/githubIntegrationLogic'

export interface GitHubIntegrationSettingsProps {
    teamId: number
}

export function GitHubIntegrationSettings({ teamId }: GitHubIntegrationSettingsProps): JSX.Element {
    const logicProps: GitHubIntegrationLogicProps = { teamId }
    const logic = githubIntegrationLogic(logicProps)
    const {
        integration,
        integrationStatus,
        isLoading,
        isSaving,
        isTesting,
        testResult,
        formValues,
    } = useValues(logic)
    const {
        loadIntegrationStatus,
        createOrUpdateIntegration,
        testConnection,
        setFormValue,
        resetForm,
    } = useActions(logic)

    useEffect(() => {
        loadIntegrationStatus()
    }, [])

    const handleSubmit = async () => {
        await createOrUpdateIntegration(formValues)
    }

    const handleTestConnection = async () => {
        if (integration?.id) {
            await testConnection(integration.id)
        }
    }

    const isConfigured = integrationStatus?.configured
    const hasUnsavedChanges = JSON.stringify(formValues) !== JSON.stringify(integration)

    return (
        <div className="space-y-6">
            <div className="flex items-center gap-2">
                <IconGithub className="text-2xl" />
                <h2 className="text-xl font-semibold">GitHub Integration</h2>
                {isConfigured && (
                    <div className="flex items-center gap-1 text-sm">
                        {integrationStatus?.active ? (
                            <>
                                <span className="text-success">✓</span>
                                <span className="text-success">Active</span>
                            </>
                        ) : (
                            <>
                                <span className="text-danger">✗</span>
                                <span className="text-danger">Inactive</span>
                            </>
                        )}
                    </div>
                )}
            </div>

            <LemonCard className="p-6">
                <div className="space-y-4">
                    <div>
                        <h3 className="text-lg font-medium mb-2">Repository Configuration</h3>
                        <p className="text-muted mb-4">
                            Configure the GitHub repository where the agent will create branches and pull requests.
                        </p>
                    </div>

                    <div className="space-y-1">
                        <LemonLabel>Repository URL</LemonLabel>
                        <LemonInput
                            value={formValues.repo_url || ''}
                            onChange={(value) => setFormValue('repo_url', value)}
                            placeholder="https://github.com/owner/repository"
                            disabled={isLoading}
                        />
                    </div>

                    <div className="grid grid-cols-2 gap-4">
                        <div className="space-y-1">
                            <LemonLabel>Repository Owner</LemonLabel>
                            <LemonInput
                                value={formValues.repo_owner || ''}
                                onChange={(value) => setFormValue('repo_owner', value)}
                                placeholder="owner"
                                disabled={isLoading}
                            />
                        </div>

                        <div className="space-y-1">
                            <LemonLabel>Repository Name</LemonLabel>
                            <LemonInput
                                value={formValues.repo_name || ''}
                                onChange={(value) => setFormValue('repo_name', value)}
                                placeholder="repository"
                                disabled={isLoading}
                            />
                        </div>
                    </div>

                    <div className="grid grid-cols-2 gap-4">
                        <div className="space-y-1">
                            <LemonLabel>Default Branch</LemonLabel>
                            <LemonInput
                                value={formValues.default_branch || 'main'}
                                onChange={(value) => setFormValue('default_branch', value)}
                                placeholder="main"
                                disabled={isLoading}
                            />
                        </div>

                        <div className="space-y-1">
                            <LemonLabel>Branch Prefix</LemonLabel>
                            <LemonInput
                                value={formValues.branch_prefix || 'issue'}
                                onChange={(value) => setFormValue('branch_prefix', value)}
                                placeholder="issue"
                                disabled={isLoading}
                            />
                        </div>
                    </div>

                    <LemonDivider />

                    <div>
                        <h3 className="text-lg font-medium mb-2">Authentication</h3>
                        <p className="text-muted mb-4">
                            Provide a GitHub Personal Access Token with repository permissions.
                        </p>
                    </div>

                    <div className="space-y-1">
                        <LemonLabel>GitHub Token</LemonLabel>
                        <LemonInput
                            type="password"
                            value={formValues.github_token || ''}
                            onChange={(value) => setFormValue('github_token', value)}
                            placeholder="ghp_xxxxxxxxxxxxxxxxxxxx"
                            disabled={isLoading}
                        />
                    </div>

                    <LemonDivider />

                    <div>
                        <h3 className="text-lg font-medium mb-2">Settings</h3>
                    </div>

                    <div className="space-y-1">
                        <LemonLabel>Auto-create Pull Requests</LemonLabel>
                        <LemonSwitch
                            checked={formValues.auto_create_pr ?? true}
                            onChange={(checked) => setFormValue('auto_create_pr', checked)}
                            label="Automatically create pull requests when agent completes work"
                            disabled={isLoading}
                        />
                    </div>

                    <div className="space-y-1">
                        <LemonLabel>Enable Integration</LemonLabel>
                        <LemonSwitch
                            checked={formValues.is_active ?? true}
                            onChange={(checked) => setFormValue('is_active', checked)}
                            label="Enable GitHub integration for issue tracking"
                            disabled={isLoading}
                        />
                    </div>

                    <LemonDivider />

                    <div className="flex justify-between items-center">
                        <div className="flex gap-2">
                            <LemonButton
                                type="primary"
                                onClick={handleSubmit}
                                loading={isSaving}
                                disabled={isLoading || !hasUnsavedChanges}
                            >
                                {isConfigured ? 'Update Integration' : 'Save Integration'}
                            </LemonButton>

                            {hasUnsavedChanges && (
                                <LemonButton type="secondary" onClick={resetForm} disabled={isLoading}>
                                    Reset
                                </LemonButton>
                            )}
                        </div>

                        {isConfigured && (
                            <LemonButton
                                type="secondary"
                                icon={<IconRefresh />}
                                onClick={handleTestConnection}
                                loading={isTesting}
                                disabled={isLoading || !integrationStatus?.has_token}
                            >
                                Test Connection
                            </LemonButton>
                        )}
                    </div>

                    {testResult && (
                        <div
                            className={`p-3 rounded border ${
                                testResult.success
                                    ? 'bg-success-highlight border-success'
                                    : 'bg-danger-highlight border-danger'
                            }`}
                        >
                            <div className="flex items-center gap-2">
                                {testResult.success ? (
                                    <span className="text-success">✓</span>
                                ) : (
                                    <span className="text-danger">✗</span>
                                )}
                                <span className="font-medium">
                                    {testResult.success ? 'Connection successful!' : 'Connection failed'}
                                </span>
                            </div>
                            {testResult.message && <p className="mt-1 text-sm">{testResult.message}</p>}
                            {testResult.error && <p className="mt-1 text-sm text-danger">{testResult.error}</p>}
                            {testResult.repository && (
                                <div className="mt-2 text-sm">
                                    <p>
                                        <strong>Repository:</strong> {testResult.repository.name}
                                    </p>
                                    <p>
                                        <strong>Default branch:</strong> {testResult.repository.default_branch}
                                    </p>
                                    <p>
                                        <strong>Private:</strong> {testResult.repository.private ? 'Yes' : 'No'}
                                    </p>
                                </div>
                            )}
                        </div>
                    )}
                </div>
            </LemonCard>

            {isConfigured && (
                <LemonCard className="p-6">
                    <div>
                        <h3 className="text-lg font-medium mb-2">Integration Status</h3>
                        <div className="space-y-2 text-sm">
                            <div className="flex justify-between">
                                <span>Repository:</span>
                                <span>{integrationStatus?.repository || 'Not configured'}</span>
                            </div>
                            <div className="flex justify-between">
                                <span>Authentication:</span>
                                <span className={integrationStatus?.has_token ? 'text-success' : 'text-danger'}>
                                    {integrationStatus?.has_token ? 'Token configured' : 'No token'}
                                </span>
                            </div>
                            <div className="flex justify-between">
                                <span>Auto-create PRs:</span>
                                <span>{integrationStatus?.auto_create_pr ? 'Enabled' : 'Disabled'}</span>
                            </div>
                            <div className="flex justify-between">
                                <span>Status:</span>
                                <span className={integrationStatus?.active ? 'text-success' : 'text-danger'}>
                                    {integrationStatus?.active ? 'Active' : 'Inactive'}
                                </span>
                            </div>
                        </div>
                    </div>
                </LemonCard>
            )}

            <LemonCard className="p-6 bg-accent-3000">
                <div>
                    <h3 className="text-lg font-medium mb-2">How it works</h3>
                    <div className="text-sm text-muted space-y-2">
                        <p>
                            1. When you move an issue to the "To Do" column, the agent will automatically clone your
                            repository
                        </p>
                        <p>2. A new branch will be created with the format: {formValues.branch_prefix || 'issue'}/issue-title-abc123</p>
                        <p>3. The agent will analyze the issue and make appropriate code changes</p>
                        <p>4. Changes will be committed and pushed to the branch</p>
                        <p>5. {formValues.auto_create_pr ? 'A pull request will be automatically created' : 'You can manually create a pull request'}</p>
                    </div>
                </div>
            </LemonCard>
        </div>
    )
}