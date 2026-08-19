import { useActions, useValues } from 'kea'

import { IconGithub } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonModal, LemonTextArea } from '@posthog/lemon-ui'

import { GitHubRepositoryPicker } from 'lib/integrations/GitHubIntegrationHelpers'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { urls } from 'scenes/urls'

import { featureDiscoveryLogic } from '../../logics/featureDiscoveryLogic'

export function FeatureDiscoveryModal(): JSX.Element {
    const {
        discoveryModalOpen,
        repository,
        repositoryForDiscovery,
        focus,
        githubIntegration,
        integrationsLoading,
        discoveryStartLoading,
    } = useValues(featureDiscoveryLogic)
    const { closeDiscoveryModal, setRepository, setFocus, startDiscovery } = useActions(featureDiscoveryLogic)

    return (
        <LemonModal
            isOpen={discoveryModalOpen}
            onClose={closeDiscoveryModal}
            title="Discover features"
            description="Choose a repository. An agent will explore it and stage feature reports for you to review."
            footer={
                <>
                    <LemonButton
                        type="secondary"
                        onClick={closeDiscoveryModal}
                        disabledReason={discoveryStartLoading ? 'Starting…' : undefined}
                    >
                        Cancel
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        onClick={startDiscovery}
                        loading={discoveryStartLoading}
                        disabledReason={
                            !repository
                                ? 'Select a repository first'
                                : !repositoryForDiscovery
                                  ? 'Reconnect GitHub to identify the repository owner'
                                  : undefined
                        }
                    >
                        Discover features
                    </LemonButton>
                </>
            }
        >
            <div className="flex flex-col gap-4">
                {githubIntegration ? (
                    <LemonField.Pure label="Repository">
                        <GitHubRepositoryPicker
                            integrationId={githubIntegration.id}
                            value={repository}
                            onChange={setRepository}
                        />
                    </LemonField.Pure>
                ) : !integrationsLoading ? (
                    <LemonBanner type="warning">
                        Connect GitHub before discovering features.
                        <LemonButton
                            type="secondary"
                            size="small"
                            icon={<IconGithub />}
                            to={urls.settings('environment-integrations', 'integration-github')}
                            className="ml-2"
                        >
                            Connect GitHub
                        </LemonButton>
                    </LemonBanner>
                ) : null}
                <LemonField.Pure
                    label="Focus"
                    info="Optional. Limit discovery to a product area, workflow, or type of feature."
                >
                    <LemonTextArea
                        value={focus}
                        onChange={setFocus}
                        minRows={3}
                        placeholder="Only discover features around session replay ingestion"
                    />
                </LemonField.Pure>
            </div>
        </LemonModal>
    )
}
