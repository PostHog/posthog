import { LemonButton, LemonDialog, LemonInput, LemonMenu, LemonTextArea } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'

import { ErrorTrackingRelationalIssue } from '~/queries/schema/schema-general'
import { IntegrationKind, IntegrationType } from '~/types'
import { urls } from 'scenes/urls'
import { integrationsLogic } from 'lib/integrations/integrationsLogic'
import { errorTrackingIssueSceneLogic } from '../errorTrackingIssueSceneLogic'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LinearTeamSelectField } from 'lib/integrations/LinearIntegrationHelpers'
import { ICONS } from 'lib/integrations/utils'
import { GitHubRepositorySelectField } from 'lib/integrations/GitHubIntegrationHelpers'

type onSubmitFormType = (integrationId: number, config: Record<string, string>) => void

export const ConnectIssueButton = (): JSX.Element | null => {
    const { issue, issueLoading } = useValues(errorTrackingIssueSceneLogic)
    const { createExternalReference } = useActions(errorTrackingIssueSceneLogic)
    const { getIntegrationsByKind, integrationsLoading } = useValues(integrationsLogic)

    if (!issue || integrationsLoading) {
        return null
    }

    const errorTrackingIntegrations = getIntegrationsByKind(['linear', 'github'])
    const externalReferences = issue.external_issues ?? []

    const onClickCreateIssue = (integration: IntegrationType): void => {
        if (integration.kind === 'github') {
            createGitHubIssueForm(issue, integration, createExternalReference)
        } else if (integration && integration.kind === 'linear') {
            createLinearIssueForm(issue, integration, createExternalReference)
        }
    }

    if (externalReferences.length > 0) {
        const reference = externalReferences[0]
        return (
            <LemonButton
                type="secondary"
                to={reference.external_url}
                targetBlank
                loading={issueLoading}
                icon={<IntegrationIcon kind={reference.integration.kind} />}
            >
                {reference.integration.display_name}
            </LemonButton>
        )
    } else if (errorTrackingIntegrations.length == 1) {
        const integration = errorTrackingIntegrations[0]
        return (
            <LemonButton
                type="secondary"
                onClick={() => onClickCreateIssue(integration)}
                loading={issueLoading}
                icon={<IntegrationIcon kind={integration.kind} />}
            >
                {issue && issueLoading ? 'Creating issue...' : 'Create issue'}
            </LemonButton>
        )
    } else if (errorTrackingIntegrations.length >= 1) {
        const items = errorTrackingIntegrations.map((integration) => ({
            label: (
                <div className="flex items-center gap-2">
                    <IntegrationIcon kind={integration.kind} />
                    <span>{integration.display_name}</span>
                </div>
            ),
            onClick: () => onClickCreateIssue(integration),
        }))

        return (
            <LemonMenu items={items} matchWidth>
                <LemonButton type="secondary" loading={issueLoading}>
                    Create external issue
                </LemonButton>
            </LemonMenu>
        )
    }

    return (
        <LemonButton type="secondary" to={urls.errorTrackingConfiguration({ tab: 'error-tracking-integrations' })}>
            Setup integrations
        </LemonButton>
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

const IntegrationIcon = ({ kind }: { kind: IntegrationKind }): JSX.Element => {
    return <img src={ICONS[kind]} className="w-5 h-5 rounded-sm" />
}
