import { LemonButton, LemonDialog, LemonInput, LemonSelect, LemonTextArea } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'

import { ErrorTrackingExternalReference, ErrorTrackingRelationalIssue } from '~/queries/schema/schema-general'
import { IntegrationType } from '~/types'
import { urls } from 'scenes/urls'
import { integrationsLogic } from 'lib/integrations/integrationsLogic'
import { IconPlus } from '@posthog/icons'
import { errorTrackingIssueSceneLogic } from '../errorTrackingIssueSceneLogic'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LinearTeamSelectField } from 'lib/integrations/LinearIntegrationHelpers'

type onSubmitFormType = (
    title: string,
    description: string,
    integrationId: number,
    config: Record<string, string>
) => void

export const ConnectIssueButton = ({
    externalReferences,
}: {
    externalReferences: ErrorTrackingExternalReference[]
}): JSX.Element | null => {
    const { issue } = useValues(errorTrackingIssueSceneLogic)
    const { createExternalReference } = useActions(errorTrackingIssueSceneLogic)
    const { linearIntegrations, githubIntegrations, integrationsLoading } = useValues(integrationsLogic)

    const errorTrackingIntegrations = [...linearIntegrations, ...githubIntegrations]

    if (!issue || integrationsLoading) {
        return null
    }

    if (externalReferences.length === 1) {
        const reference = externalReferences[0]

        return (
            <LemonButton type="secondary" to={reference.external_url} tooltip={reference.integration.display_name}>
                {reference.integration.display_name} issue
            </LemonButton>
        )
    } else if (errorTrackingIntegrations.length === 1) {
        const integration = errorTrackingIntegrations[0]

        return (
            <LemonButton
                icon={<IconPlus />}
                type="secondary"
                onClick={() => createLinearIssueForm(issue, integration, createExternalReference)}
            >
                Create {integration.display_name} issue
            </LemonButton>
        )
    } else if (errorTrackingIntegrations.length > 1) {
        return (
            <LemonSelect
                placeholder="Create external issue"
                onSelect={(integrationId) => {
                    const integration = errorTrackingIntegrations.find((i) => i.id === integrationId)

                    if (integration) {
                        if (integration.kind === 'github') {
                            // TODO
                        } else if (integration && integration.kind === 'linear') {
                            createLinearIssueForm(issue, integration, createExternalReference)
                        }
                    }
                }}
                options={errorTrackingIntegrations.map((i) => ({
                    label: i.display_name,
                    value: i.id,
                }))}
            />
        )
    }

    return (
        <LemonButton type="secondary" to={urls.errorTrackingConfiguration({ tab: 'error-tracking-integrations' })}>
            Connect issue
        </LemonButton>
    )
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
            onSubmit(title, description, integration.id, { team_id: teamIds[0] })
        },
    })
}
