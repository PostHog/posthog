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

    return (
        <LemonButton
            size={size}
            icon={<IconWrench />}
            tooltip="Create a task and start a fix agent on it"
            onClick={() => openCreateFixTaskForm(context, getIntegrationsByKind(['github']))}
        >
            Create fix task
        </LemonButton>
    )
}

function openCreateFixTaskForm(context: MCPErrorContext, githubIntegrations: IntegrationType[]): void {
    const bucket = context.errorStatus ? `${context.errorType} (HTTP ${context.errorStatus})` : context.errorType
    const defaultIntegration = githubIntegrations[0]

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
                {githubIntegrations.length > 0 && <GitHubRepositorySelectField integrationId={defaultIntegration.id} />}
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
                githubIntegrations.length > 0 && (!repositories || repositories.length === 0)
                    ? 'You must choose a repository'
                    : undefined,
        },
        onSubmit: async ({ title, description, repositories }) => {
            const taskData: TaskUpsertProps = {
                title,
                description,
                origin_product: OriginProduct.MCP_ANALYTICS,
            }

            const repoName = repositories?.[0]
            if (defaultIntegration && repoName && typeof repoName === 'string') {
                taskData.github_integration = defaultIntegration.id
                taskData.repository = repoName.includes('/')
                    ? repoName
                    : `${
                          defaultIntegration.config?.account?.name ||
                          defaultIntegration.config?.account?.login ||
                          'GitHub'
                      }/${repoName}`
            }

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
