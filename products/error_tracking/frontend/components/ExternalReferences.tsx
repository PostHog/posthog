import { LemonDialog, LemonInput, LemonSkeleton, LemonTextArea, Link, LemonSelect } from '@posthog/lemon-ui'

import { useActions, useValues } from 'kea'

import { ErrorTrackingRelationalIssue } from '~/queries/schema/schema-general'
import { IntegrationKind, IntegrationType } from '~/types'
import { ErrorEventType } from 'lib/components/Errors/types'
import { urls } from 'scenes/urls'
import { integrationsLogic } from 'lib/integrations/integrationsLogic'
import { errorTrackingIssueSceneLogic } from '../errorTrackingIssueSceneLogic'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LinearTeamSelectField } from 'lib/integrations/LinearIntegrationHelpers'
import { ICONS } from 'lib/integrations/utils'
import { GitHubRepositorySelectField } from 'lib/integrations/GitHubIntegrationHelpers'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import {
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuTrigger,
} from 'lib/ui/DropdownMenu/DropdownMenu'
import { IconPlus } from '@posthog/icons'
import api from 'lib/api'

const ERROR_TRACKING_INTEGRATIONS: IntegrationKind[] = ['linear', 'github']

type onSubmitFormType = (integrationId: number, config: Record<string, string>) => void

export const ExternalReferences = (): JSX.Element | null => {
    const { issue, issueLoading, selectedEvent } = useValues(errorTrackingIssueSceneLogic)
    const { createExternalReference } = useActions(errorTrackingIssueSceneLogic)
    const { getIntegrationsByKind, integrationsLoading } = useValues(integrationsLogic)

    if (!issue || integrationsLoading) {
        return <LemonSkeleton />
    }

    const errorTrackingIntegrations = getIntegrationsByKind(ERROR_TRACKING_INTEGRATIONS)
    const externalReferences = issue.external_issues ?? []
    const creatingIssue = issue && issueLoading

    const onClickCreateIssue = (integration: IntegrationType): void => {
        if (integration.kind === 'github') {
            createGitHubIssueForm(issue, integration, createExternalReference)
        } else if (integration && integration.kind === 'linear') {
            createLinearIssueForm(issue, integration, createExternalReference)
        }
    }

    const onClickCreateTask = (): void => {
        const githubIntegrations = getIntegrationsByKind(['github'])
        createTaskForm(issue, selectedEvent, githubIntegrations)
    }

    return (
        <div>
            {externalReferences.map((reference) => (
                <Link key={reference.id} to={reference.external_url} target="_blank">
                    <ButtonPrimitive fullWidth disabled={issueLoading}>
                        <IntegrationIcon kind={reference.integration.kind} />
                        {reference.integration.display_name}
                    </ButtonPrimitive>
                </Link>
            ))}
            {errorTrackingIntegrations.length === 0 ? (
                <>
                    <SetupIntegrationsButton />
                    <ButtonPrimitive
                        fullWidth
                        onClick={onClickCreateTask}
                        disabled={issueLoading}
                        style={{ marginTop: '8px' }}
                    >
                        <IconPlus />
                        Create task in PostHog
                    </ButtonPrimitive>
                </>
            ) : errorTrackingIntegrations.length > 1 ? (
                <>
                    <DropdownMenu>
                        <DropdownMenuTrigger asChild>
                            <ButtonPrimitive fullWidth disabled={creatingIssue}>
                                <IconPlus />
                                {creatingIssue ? 'Creating issue...' : 'Create issue'}
                            </ButtonPrimitive>
                        </DropdownMenuTrigger>

                        <DropdownMenuContent loop matchTriggerWidth>
                            {errorTrackingIntegrations.map((integration) => (
                                <DropdownMenuItem key={integration.id} asChild>
                                    <ButtonPrimitive menuItem onClick={() => onClickCreateIssue(integration)}>
                                        <IntegrationIcon kind={integration.kind} />
                                        {integration.display_name}
                                    </ButtonPrimitive>
                                </DropdownMenuItem>
                            ))}
                        </DropdownMenuContent>
                    </DropdownMenu>
                    <ButtonPrimitive
                        fullWidth
                        onClick={onClickCreateTask}
                        disabled={issueLoading}
                        style={{ marginTop: '8px' }}
                    >
                        <IconPlus />
                        Create task in PostHog
                    </ButtonPrimitive>
                </>
            ) : (
                <ButtonPrimitive
                    fullWidth
                    onClick={() => onClickCreateIssue(errorTrackingIntegrations[0])}
                    disabled={issueLoading}
                >
                    <IntegrationIcon kind={errorTrackingIntegrations[0].kind} />
                    {creatingIssue ? 'Creating issue...' : 'Create issue'}
                </ButtonPrimitive>
            )}
            <ButtonPrimitive fullWidth onClick={onClickCreateTask} disabled={issueLoading} style={{ marginTop: '8px' }}>
                <IconPlus />
                Create task in PostHog
            </ButtonPrimitive>
        </div>
    )
}

function SetupIntegrationsButton(): JSX.Element {
    return (
        <Link to={urls.errorTrackingConfiguration({ tab: 'error-tracking-integrations' })}>
            <ButtonPrimitive fullWidth>Setup integrations</ButtonPrimitive>
        </Link>
    )
}

const createGitHubIssueForm = (
    issue: ErrorTrackingRelationalIssue,
    integration: IntegrationType,
    onSubmit: onSubmitFormType
): void => {
    const posthogUrl = window.location.origin + window.location.pathname
    const body = issue.description + '\n<br/>\n<br/>\n' + `**PostHog issue:** ${posthogUrl}`

    LemonDialog.openForm({
        title: 'Create GitHub issue',
        initialValues: {
            title: issue.name,
            body: body,
            integrationId: integration.id,
            repositories: [],
        },
        content: (
            <div className="flex flex-col gap-y-2">
                <GitHubRepositorySelectField integrationId={integration.id} />
                <LemonField name="title" label="Title">
                    <LemonInput data-attr="issue-title" placeholder="Issue title" size="small" />
                </LemonField>
                <LemonField name="body" label="Body">
                    <LemonTextArea data-attr="issue-body" placeholder="Start typing..." />
                </LemonField>
            </div>
        ),
        errors: {
            title: (title) => (!title ? 'You must enter a title' : undefined),
            repositories: (repositories) =>
                repositories && repositories.length === 0 ? 'You must choose a repository' : undefined,
        },
        onSubmit: ({ title, body, repositories }) => {
            onSubmit(integration.id, { repository: repositories[0], title, body })
        },
    })
}

const createLinearIssueForm = (
    issue: ErrorTrackingRelationalIssue,
    integration: IntegrationType,
    onSubmit: onSubmitFormType
): void => {
    LemonDialog.openForm({
        title: 'Create Linear issue',
        initialValues: {
            title: issue.name,
            description: issue.description,
            integrationId: integration.id,
            teamIds: [],
        },
        content: (
            <div className="flex flex-col gap-y-2">
                <LinearTeamSelectField integrationId={integration.id} />
                <LemonField name="title" label="Title">
                    <LemonInput data-attr="issue-title" placeholder="Issue title" size="small" />
                </LemonField>
                <LemonField name="description" label="Description">
                    <LemonTextArea data-attr="issue-description" placeholder="Start typing..." />
                </LemonField>
            </div>
        ),
        errors: {
            title: (title) => (!title ? 'You must enter a title' : undefined),
            teamIds: (teamIds) => (teamIds && teamIds.length === 0 ? 'You must choose a team' : undefined),
        },
        onSubmit: ({ title, description, teamIds }) => {
            onSubmit(integration.id, { team_id: teamIds[0], title, description })
        },
    })
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
            const exception = props.$exception_list[0]

            description += `## ${exception.type}: ${exception.value}\n\n`

            if (exception.mechanism) {
                description += `**Handled:** ${exception.mechanism.handled ? 'Yes' : 'No'}\n\n`
            }

            // Add detailed stack trace from frames
            if (exception.stacktrace?.frames && Array.isArray(exception.stacktrace.frames)) {
                description += `## Stack Trace\n\n`

                const frames = exception.stacktrace.frames.slice().reverse() // Reverse to show call order
                frames.forEach((frame, index) => {
                    description += `**${index + 1}.** `
                    if (frame.mangled_name && frame.mangled_name !== '?') {
                        description += `\`${frame.mangled_name}\``
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
    if (issue.last_seen) {
        description += `**Last Seen:** ${new Date(issue.last_seen).toLocaleString()}`
    }

    const defaultIntegration = githubIntegrations[0]

    LemonDialog.openForm({
        title: 'Create PostHog task',
        initialValues: {
            title: issue.name,
            description: description,
            status: 'todo',
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
                <LemonField name="status" label="Priority">
                    <LemonSelect
                        data-attr="task-status"
                        options={[
                            { value: 'todo', label: 'Fix now (Todo)' },
                            { value: 'backlog', label: 'Add to backlog' },
                        ]}
                    />
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
        onSubmit: async ({ title, description, status, repositories }) => {
            try {
                const taskData: any = {
                    title,
                    description,
                    status,
                    origin_product: 'error_tracking',
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
                    } else {
                    }
                } else {
                }

                await api.tasks.create(taskData)
            } catch (error) {
                console.error('Failed to create task:', error)
            }
        },
    })
}

const IntegrationIcon = ({ kind }: { kind: IntegrationKind }): JSX.Element => {
    return <img src={ICONS[kind]} className="w-5 h-5 rounded-sm" />
}
