import { useValues } from 'kea'

import { IconWrench } from '@posthog/icons'
import { LemonButton, LemonDialog, LemonInput, LemonTextArea, lemonToast } from '@posthog/lemon-ui'

import api from 'lib/api'
import { GitHubRepositorySelectField } from 'lib/integrations/GitHubIntegrationHelpers'
import { integrationsLogic } from 'lib/integrations/integrationsLogic'
import { LemonField } from 'lib/lemon-ui/LemonField'

import { IntegrationType } from '~/types'

import { OriginProduct, TaskUpsertProps } from 'products/posthog_ai/frontend/types/taskTypes'

import { type MCPErrorContext, formatErrorContext } from './errorContext'

// Mirrors error tracking's IssueTasks button: create a task prefilled with the failure
// context, then immediately start an agent run on it (REST create does not auto-run).
export function CreateFixTaskButton({
    context,
    size = 'xsmall',
}: {
    context: MCPErrorContext
    size?: 'xsmall' | 'small' | 'medium'
}): JSX.Element {
    const { getIntegrationsByKind } = useValues(integrationsLogic)
    const githubIntegrations = getIntegrationsByKind(['github'])

    return (
        <LemonButton
            size={size}
            icon={<IconWrench />}
            tooltip="Create a task and start a fix agent on it"
            // Without a repository the agent has no codebase to fix, so a task must not start.
            disabledReason={
                githubIntegrations.length === 0
                    ? 'Connect the GitHub integration (Settings → Integrations) to give the fix agent a repository'
                    : undefined
            }
            onClick={() => openCreateFixTaskForm(context, githubIntegrations)}
        >
            Create fix task
        </LemonButton>
    )
}

function openCreateFixTaskForm(context: MCPErrorContext, githubIntegrations: IntegrationType[]): void {
    const bucket = context.errorStatus ? `${context.errorType} (HTTP ${context.errorStatus})` : context.errorType
    const defaultIntegration = githubIntegrations[0]
    // The button is disabled without an integration, but guard anyway: this function
    // dereferences the integration unconditionally and must not crash if reached.
    if (!defaultIntegration) {
        lemonToast.error('Connect the GitHub integration (Settings → Integrations) before creating a fix task')
        return
    }

    LemonDialog.openForm({
        title: 'Create fix task',
        description: 'The task starts a coding agent with this context. Review before creating.',
        shouldAwaitSubmit: true,
        initialValues: {
            title: `Fix MCP tool failure: ${context.toolName} (${bucket})`,
            description: formatErrorContext(context),
            repositories: [],
        },
        content: (
            <div className="flex flex-col gap-y-4">
                <GitHubRepositorySelectField integrationId={defaultIntegration.id} />
                <LemonField name="title" label="Title">
                    <LemonInput data-attr="mcp-fix-task-title" placeholder="Task title" size="small" />
                </LemonField>
                <LemonField name="description" label="Description">
                    <LemonTextArea data-attr="mcp-fix-task-description" placeholder="Start typing..." rows={10} />
                </LemonField>
            </div>
        ),
        errors: {
            title: (title) => (!title ? 'You must enter a title' : undefined),
            repositories: (repositories) =>
                !repositories || repositories.length === 0 ? 'You must choose a repository' : undefined,
        },
        onSubmit: async ({ title, description, repositories }) => {
            const taskData: TaskUpsertProps = {
                title,
                description,
                origin_product: OriginProduct.MCP_ANALYTICS,
            }

            const repoName = repositories?.[0]
            if (!repoName || typeof repoName !== 'string') {
                lemonToast.error('You must choose a repository')
                throw new Error('No repository selected')
            }
            const owner = defaultIntegration.config?.account?.name || defaultIntegration.config?.account?.login
            if (!repoName.includes('/') && !owner) {
                // Never guess the owner half of "owner/repo" — a made-up full name sends
                // the agent to a repository that doesn't exist.
                lemonToast.error('Could not determine the repository owner from the GitHub integration')
                throw new Error('Unknown repository owner')
            }
            taskData.github_integration = defaultIntegration.id
            taskData.repository = repoName.includes('/') ? repoName : `${owner}/${repoName}`

            let task
            try {
                task = await api.tasks.create(taskData)
            } catch (error) {
                lemonToast.error('Failed to create the task')
                throw error
            }
            try {
                await api.tasks.run(task.id)
                lemonToast.success('Fix task created and agent run started')
            } catch {
                lemonToast.warning('Task created, but the agent run could not be started')
            }
        },
    })
}
