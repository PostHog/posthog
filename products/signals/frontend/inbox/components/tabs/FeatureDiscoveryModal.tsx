import { useActions, useValues } from 'kea'

import { IconGithub } from '@posthog/icons'
import { LemonBadge, LemonBanner, LemonButton, LemonCard, LemonModal, LemonTextArea, Link } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { GitHubRepositoryPicker } from 'lib/integrations/GitHubIntegrationHelpers'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { urls } from 'scenes/urls'

import { featureDiscoveryLogic } from '../../logics/featureDiscoveryLogic'
import { featureListLogic } from '../../logics/featureListLogic'

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
    const { features } = useValues(featureListLogic)
    const { closeDiscoveryModal, setRepository, setFocus, startDiscovery } = useActions(featureDiscoveryLogic)
    const discoveredFeatures = features.filter((feature) => feature.feature_stage === 'staged')

    return (
        <LemonModal
            isOpen={discoveryModalOpen}
            onClose={closeDiscoveryModal}
            title="Discover features"
            description="Choose a repository for an agent to explore. Discovered feature reports will appear below for review."
            width={720}
            footer={
                <>
                    <LemonButton
                        type="secondary"
                        onClick={closeDiscoveryModal}
                        disabledReason={discoveryStartLoading ? 'Starting…' : undefined}
                    >
                        Close
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

                <section className="flex flex-col gap-2 border-t pt-4">
                    <div>
                        <div className="flex items-center gap-2">
                            <h3 className="mb-0">Discovered features</h3>
                            <LemonBadge.Number
                                count={discoveredFeatures.length}
                                maxDigits={3}
                                showZero
                                size="small"
                                status="muted"
                            />
                        </div>
                        <p className="mb-0 text-sm text-muted">
                            Review features found in connected repositories before making them live.
                        </p>
                    </div>

                    {discoveredFeatures.length === 0 ? (
                        <LemonCard hoverEffect={false} className="border-dashed p-4">
                            <p className="mb-0 text-sm text-muted">
                                No discovered features yet. Choose a repository and start discovery.
                            </p>
                        </LemonCard>
                    ) : (
                        discoveredFeatures.map((feature) => (
                            <Link
                                key={feature.id}
                                to={urls.inboxReport('features', feature.id)}
                                onClick={closeDiscoveryModal}
                                className="block rounded text-inherit no-underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
                            >
                                <LemonCard className="flex flex-col gap-1 p-4">
                                    <span className="min-w-0 break-words text-sm font-semibold leading-snug">
                                        {feature.title || 'Untitled feature'}
                                    </span>
                                    {feature.summary && (
                                        <span className="line-clamp-2 text-sm text-muted">{feature.summary}</span>
                                    )}
                                    <TZLabel time={feature.updated_at} className="text-xs text-muted" />
                                </LemonCard>
                            </Link>
                        ))
                    )}
                </section>
            </div>
        </LemonModal>
    )
}
