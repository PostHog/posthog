import { LemonButton, LemonDialog, LemonInput, LemonModal, LemonSelect, LemonTextArea } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'

import { ErrorTrackingExternalReference } from '~/queries/schema/schema-general'
import { IntegrationKind } from '~/types'
import { urls } from 'scenes/urls'
import { integrationsLogic } from 'lib/integrations/integrationsLogic'
import { IconPlus } from '@posthog/icons'
import { IconArrowDown } from 'lib/lemon-ui/icons'
import { errorTrackingIssueSceneLogic } from '../errorTrackingIssueSceneLogic'
import { LemonField } from 'lib/lemon-ui/LemonField'

export const IssueExternalReferenceCreationModal = (): JSX.Element | null => {
    return <LemonModal></LemonModal>
}

export const ConnectIssueButton = ({
    externalIssues,
}: {
    externalIssues: ErrorTrackingExternalReference[]
}): JSX.Element => {
    const { issue } = useValues(errorTrackingIssueSceneLogic)
    const { createExternalReference } = useActions(errorTrackingIssueSceneLogic)
    const { linearIntegrations, githubIntegrations } = useValues(integrationsLogic)

    const errorTrackingIntegrations = [...linearIntegrations, ...githubIntegrations]

    if (externalIssues.length === 1) {
        const kind = externalIssues[0].provider

        return (
            <LemonButton
                type="secondary"
                onClick={() => console.log('Create issue')}
                sideAction={{
                    icon: <IconArrowDown />,
                    dropdown: {
                        overlay: <LemonButton onClick={() => console.log('Unlink issue')}>Unlink</LemonButton>,
                    },
                }}
            >
                {kind} issue
            </LemonButton>
        )
    } else if (errorTrackingIntegrations.length > 0) {
        const integration = errorTrackingIntegrations[0]
        const kind = getProviderFromIntegrationKind(integration.kind)

        return (
            <LemonButton
                icon={<IconPlus />}
                type="secondary"
                onClick={() => {
                    if (issue) {
                        LemonDialog.openForm({
                            title: 'Create issue',
                            initialValues: {
                                title: issue.name,
                                description: issue.description,
                                integration: errorTrackingIntegrations[0],
                                config: {},
                            },
                            content: ({ values }) => {
                                console.log(values)
                                return (
                                    <div className="flex flex-col gap-y-2">
                                        {errorTrackingIntegrations.length > 1 && (
                                            <LemonField name="integration">
                                                <LemonSelect
                                                    size="small"
                                                    options={errorTrackingIntegrations.map((i) => ({
                                                        label: i.display_name,
                                                        value: i,
                                                    }))}
                                                    className="w-30"
                                                />
                                            </LemonField>
                                        )}
                                        {/* {values?.integration?.kind == 'linear' && <p>Linear integration choose team</p>} */}
                                        <LemonField name="title">
                                            <LemonInput
                                                data-attr="issue-title"
                                                placeholder="Issue title"
                                                size="small"
                                            />
                                        </LemonField>
                                        <LemonField name="description">
                                            <LemonTextArea
                                                data-attr="issue-description"
                                                placeholder="Start typing..."
                                            />
                                        </LemonField>
                                        {integration.kind == 'linear' && <LinearConfig />}
                                    </div>
                                )
                            },
                            errors: {
                                title: (title) => (!title ? 'You must enter a title' : undefined),
                            },
                            onSubmit: ({ title, description, integration }) =>
                                createExternalReference(title, description, integration),
                        })
                    }
                }}
            >
                Create {kind} issue
            </LemonButton>
        )
    }

    return (
        <LemonButton type="secondary" to={urls.errorTrackingConfiguration({ tab: 'error-tracking-integrations' })}>
            Connect issue
        </LemonButton>
    )
}

const LinearConfig = (): JSX.Element => {
    return (
        <LemonField name="config">
            <LemonSelect
                size="small"
                fullWidth
                options={[
                    { id: 1, name: 'Team 1' },
                    { id: 2, name: 'Team 2' },
                ].map((i) => ({
                    label: i.name,
                    value: i,
                }))}
            />
        </LemonField>
    )
}

const getProviderFromIntegrationKind = (kind: IntegrationKind): string => {
    if (kind === 'linear') {
        return 'Linear'
    } else if (kind === 'github') {
        return 'GitHub'
    } else {
        throw Error('Not a valid error tracking external provider type')
    }
}
