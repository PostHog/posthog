import { LemonButton, LemonDialog, LemonInput, LemonMenu, LemonMenuItem, LemonTextArea } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'

import {
    ErrorTrackingExternalReference,
    ErrorTrackingExternalReferenceIntegration,
    ErrorTrackingRelationalIssue,
} from '~/queries/schema/schema-general'
import { IntegrationType } from '~/types'
import { urls } from 'scenes/urls'
import { integrationsLogic } from 'lib/integrations/integrationsLogic'
import { errorTrackingIssueSceneLogic } from '../errorTrackingIssueSceneLogic'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LinearTeamSelectField } from 'lib/integrations/LinearIntegrationHelpers'
import { getIntegrationNameFromKind } from 'lib/integrations/utils'
import { IconPlus } from '@posthog/icons'

type onSubmitFormType = (integrationId: number, config: Record<string, string>) => void

export const ConnectIssueButton = ({
    externalReferences,
}: {
    externalReferences: ErrorTrackingExternalReference[]
}): JSX.Element | null => {
    const { issue, issueLoading } = useValues(errorTrackingIssueSceneLogic)
    const { createExternalReference } = useActions(errorTrackingIssueSceneLogic)
    const { getIntegrationsByKind, integrationsLoading } = useValues(integrationsLogic)

    const errorTrackingIntegrations = getIntegrationsByKind(['linear', 'github'])

    if (!issue || integrationsLoading) {
        return null
    }

    if (externalReferences.length === 1) {
        const reference = externalReferences[0]

        return (
            <LemonButton type="secondary" to={reference.external_url} targetBlank loading={issueLoading}>
                {integrationLabel(reference.integration)}
            </LemonButton>
        )
    } else if (errorTrackingIntegrations.length >= 1) {
        const onClick = (integration: IntegrationType): void => {
            if (integration.kind === 'github') {
                // TODO
            } else if (integration && integration.kind === 'linear') {
                createLinearIssueForm(issue, integration, createExternalReference)
            }
        }

        return (
            <LemonMenu
                items={[
                    {
                        items: errorTrackingIntegrations.map((i) => ({
                            label: integrationLabel(i),
                            onClick: () => onClick(i),
                        })) as LemonMenuItem[],
                    },
                    {
                        items: [
                            {
                                to: urls.errorTrackingConfiguration({ tab: 'error-tracking-integrations' }),
                                label: 'Add integration',
                                sideIcon: <IconPlus />,
                            },
                        ],
                    },
                ]}
            >
                <LemonButton type="secondary">Create external issue</LemonButton>
            </LemonMenu>
        )
    }

    return (
        <LemonButton type="secondary" to={urls.errorTrackingConfiguration({ tab: 'error-tracking-integrations' })}>
            Setup integrations
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
            onSubmit(integration.id, { team_id: teamIds[0], title, description })
        },
    })
}

const integrationLabel = (i: ErrorTrackingExternalReferenceIntegration): string => {
    return `${i.display_name} (${getIntegrationNameFromKind(i.kind)})`
}
