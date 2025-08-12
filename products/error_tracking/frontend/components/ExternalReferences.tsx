import { LemonDialog, LemonInput, LemonTextArea, Link } from '@posthog/lemon-ui'
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
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import {
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuTrigger,
} from 'lib/ui/DropdownMenu/DropdownMenu'
import { IconPlus } from '@posthog/icons'
import { WrappingLoadingSkeleton } from 'lib/ui/WrappingLoadingSkeleton/WrappingLoadingSkeleton'

const ERROR_TRACKING_INTEGRATIONS: IntegrationKind[] = ['linear', 'github']

type onSubmitFormType = (integrationId: number, config: Record<string, string>) => void

export const ExternalReferences = (): JSX.Element | null => {
    const { issue, issueLoading } = useValues(errorTrackingIssueSceneLogic)
    const { createExternalReference } = useActions(errorTrackingIssueSceneLogic)
    const { getIntegrationsByKind, integrationsLoading } = useValues(integrationsLogic)

    if (!issue || integrationsLoading) {
        return (
            <WrappingLoadingSkeleton fullWidth>
                <ButtonPrimitive menuItem aria-hidden>
                    Loading
                </ButtonPrimitive>
            </WrappingLoadingSkeleton>
        )
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
                <SetupIntegrationsButton />
            ) : errorTrackingIntegrations.length > 1 ? (
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
        </div>
    )
}

function SetupIntegrationsButton(): JSX.Element {
    return (
        <Link
            to={urls.errorTrackingConfiguration({ tab: 'error-tracking-integrations' })}
            buttonProps={{ variant: 'panel', fullWidth: true, menuItem: true }}
            tooltip="Go to integrations configuration"
        >
            Setup integrations
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

const IntegrationIcon = ({ kind }: { kind: IntegrationKind }): JSX.Element => {
    return <img src={ICONS[kind]} className="w-5 h-5 rounded-sm" />
}
