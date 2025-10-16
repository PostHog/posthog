import { useValues } from 'kea'

import { IconPlus } from '@posthog/icons'
import { LemonDialog, LemonInput, LemonTextArea } from '@posthog/lemon-ui'

import api from 'lib/api'
import { ErrorEventType, ErrorTrackingException } from 'lib/components/Errors/types'
import { formatExceptionDisplay, formatResolvedName } from 'lib/components/Errors/utils'
import { GitHubRepositorySelectField } from 'lib/integrations/GitHubIntegrationHelpers'
import { integrationsLogic } from 'lib/integrations/integrationsLogic'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'

import { ScenePanelLabel } from '~/layout/scenes/SceneLayout'
import { ErrorTrackingRelationalIssue } from '~/queries/schema/schema-general'
import { IntegrationType } from '~/types'

import { OriginProduct, TaskUpsertProps } from 'products/tasks/frontend/types'

import { errorTrackingIssueSceneLogic } from '../scenes/ErrorTrackingIssueScene/errorTrackingIssueSceneLogic'

export const IssueTasks = (): JSX.Element => {
    const { issue, issueLoading, selectedEvent } = useValues(errorTrackingIssueSceneLogic)
    const { getIntegrationsByKind } = useValues(integrationsLogic)

    const onClickCreateTask = (): void => {
        if (issue) {
            const githubIntegrations = getIntegrationsByKind(['github'])
            createTaskForm(issue, selectedEvent, githubIntegrations)
        }
    }
    return (
        <ScenePanelLabel title="Tasks">
            <ButtonPrimitive fullWidth onClick={onClickCreateTask} disabled={issueLoading} variant="panel">
                <IconPlus />
                Create task in PostHog
            </ButtonPrimitive>
        </ScenePanelLabel>
    )
}

const createTaskForm = (
    issue: ErrorTrackingRelationalIssue,
    selectedEvent: ErrorEventType | null,
    githubIntegrations: IntegrationType[]
): void => {
    const posthogUrl = window.location.origin + window.location.pathname

    let description = ''

    if (selectedEvent?.properties) {
        const props = selectedEvent.properties

        // Extract error details from exception list
        if (props.$exception_list && Array.isArray(props.$exception_list) && props.$exception_list.length > 0) {
            const exception = props.$exception_list[0] as ErrorTrackingException

            description += `## ${formatExceptionDisplay(exception)}\n\n`

            if (exception.mechanism) {
                description += `**Handled:** ${exception.mechanism.handled ? 'Yes' : 'No'}\n\n`
            }

            // Add detailed stack trace from frames
            if (exception.stacktrace && exception.stacktrace.type === 'resolved') {
                description += `## Stack Trace\n\n`

                const frames = exception.stacktrace.frames.slice().reverse() // Reverse to show call order
                frames.forEach((frame, index) => {
                    description += `**${index + 1}.** `
                    const resolvedName = formatResolvedName(frame)
                    if (resolvedName) {
                        description += `\`${resolvedName}\``
                    } else {
                        description += 'Anonymous function'
                    }

                    if (frame.source) {
                        description += ` in \`${frame.source}\``
                    }

                    if (frame.line) {
                        description += ` at line ${frame.line}`
                        if (frame.column) {
                            description += `:${frame.column}`
                        }
                    }

                    description += '\n'

                    // Add resolution failure if present
                    if (frame.resolve_failure) {
                        description += `   *Source map resolution failed: ${frame.resolve_failure}*\n`
                    }
                })
                description += '\n'
            }
        } else {
            // Fallback to basic error info
            description += `## ${issue.name}\n\n`
            if (props.$exception_message) {
                description += `**Message:** ${props.$exception_message}\n\n`
            }
            if (props.$exception_type) {
                description += `**Type:** ${props.$exception_type}\n\n`
            }
        }

        // Add browser/environment info
        if (props.$browser || props.$os || props.$lib_version) {
            description += `## Environment\n\n`
            if (props.$browser) {
                description += `**Browser:** ${props.$browser}\n`
            }
            if (props.$os) {
                description += `**OS:** ${props.$os}\n`
            }
            if (props.$lib_version) {
                description += `**SDK Version:** ${props.$lib_version}\n`
            }
            if (props.$viewport_height && props.$viewport_width) {
                description += `**Viewport:** ${props.$viewport_width}x${props.$viewport_height}\n`
            }
            description += '\n'
        }

        // Add URL and user info
        if (props.$current_url) {
            description += `**Page:** ${props.$current_url}\n`
        }
        if (props.$referrer) {
            description += `**Referrer:** ${props.$referrer}\n`
        }
        if (props.distinct_id) {
            description += `**User ID:** ${props.distinct_id}\n`
        }
        description += '\n'
    } else {
        description += `## ${issue.name}\n\n`
    }

    description += `---\n\n`
    description += `**PostHog Error Tracking:** ${posthogUrl}\n`
    description += `**First Seen:** ${new Date(issue.first_seen).toLocaleString()}\n`

    const defaultIntegration = githubIntegrations[0]

    LemonDialog.openForm({
        title: 'Create PostHog task',
        initialValues: {
            title: issue.name ?? '',
            description: description ?? '',
            repositories: [],
        },
        content: (
            <div className="flex flex-col gap-y-4">
                {githubIntegrations.length > 0 && <GitHubRepositorySelectField integrationId={defaultIntegration.id} />}
                <LemonField name="title" label="Title">
                    <LemonInput data-attr="task-title" placeholder="Task title" size="small" />
                </LemonField>
                <LemonField name="description" label="Description">
                    <LemonTextArea data-attr="task-description" placeholder="Start typing..." rows={8} />
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
            try {
                const taskData: TaskUpsertProps = {
                    title,
                    description,
                    origin_product: OriginProduct.ERROR_TRACKING,
                }

                // Add repository config if GitHub integration is available and repository is selected
                if (githubIntegrations.length > 0 && repositories && repositories.length > 0) {
                    const repoName = repositories[0]

                    if (repoName && typeof repoName === 'string') {
                        let organization: string
                        let repository: string

                        if (repoName.includes('/')) {
                            // Format: "owner/repo"
                            ;[organization, repository] = repoName.split('/', 2)
                        } else {
                            // Just repository name - get organization from integration config
                            organization =
                                defaultIntegration.config?.account?.name ||
                                defaultIntegration.config?.account?.login ||
                                'GitHub'
                            repository = repoName
                        }

                        taskData.github_integration = defaultIntegration.id
                        taskData.repository_config = {
                            organization,
                            repository,
                        }
                    }
                }

                await api.tasks.create(taskData)
            } catch (error) {
                console.error('Failed to create task:', error)
            }
        },
    })
}
