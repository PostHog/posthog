import { useActions, useValues } from 'kea'

import { IconPlus, IconRocket, IconSearch } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonCard, LemonSkeleton, LemonTag } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { urls } from 'scenes/urls'

import type { InboxFeatureDiscoveryRunApi } from '../../../generated/api.schemas'
import { featureCreateLogic } from '../../logics/featureCreateLogic'
import { featureDiscoveryLogic } from '../../logics/featureDiscoveryLogic'
import { featureListLogic } from '../../logics/featureListLogic'
import { FeatureDiscoveryModal } from './FeatureDiscoveryModal'
import { NewFeatureModal } from './NewFeatureModal'

export function FeatureDiscoveryBanner({ run }: { run: InboxFeatureDiscoveryRunApi }): JSX.Element {
    return (
        <LemonBanner
            type="info"
            action={{
                children: 'View task logs',
                to: run.task_id ? urls.taskDetail(run.task_id) : undefined,
                disabledReason: run.task_id ? undefined : 'Task logs are available after the agent starts.',
                'data-attr': 'feature-discovery-view-task-logs',
            }}
        >
            Discovering features in <strong>{run.repository}</strong>
            {run.focus ? ` with the focus “${run.focus}”` : ''}. The reports will appear in Staged features when the
            agent finishes.
        </LemonBanner>
    )
}

export function FeaturesTab(): JSX.Element {
    const { features, featuresLoading } = useValues(featureListLogic)
    const { openNewFeatureModal } = useActions(featureCreateLogic)
    const { discoveryRetryLoading, discoveryRuns } = useValues(featureDiscoveryLogic)
    const { openDiscoveryModal, retryDiscovery } = useActions(featureDiscoveryLogic)

    const stagedFeatures = features.filter((feature) => feature.feature_stage === 'staged')
    const ownedFeatures = features.filter((feature) => feature.feature_stage !== 'staged')
    const activeDiscoveryRuns = discoveryRuns.filter(
        (run) => run.discovery_status === 'queued' || run.discovery_status === 'running'
    )
    const latestFailedRun = discoveryRuns[0]?.discovery_status === 'failed' ? discoveryRuns[0] : undefined
    const latestEmptyRun =
        discoveryRuns[0]?.discovery_status === 'completed' && discoveryRuns[0].discovered_count === 0
            ? discoveryRuns[0]
            : undefined

    const actionButtons = (
        <div className="flex items-center gap-2">
            <LemonButton type="secondary" size="small" icon={<IconSearch />} onClick={openDiscoveryModal}>
                Discover features
            </LemonButton>
            <LemonButton type="primary" size="small" icon={<IconPlus />} onClick={openNewFeatureModal}>
                New feature
            </LemonButton>
        </div>
    )

    if (featuresLoading && features.length === 0) {
        return (
            <div className="flex flex-col gap-2 p-6">
                <LemonSkeleton className="h-16 rounded" repeat={3} />
            </div>
        )
    }

    if (features.length === 0 && activeDiscoveryRuns.length === 0 && !latestFailedRun && !latestEmptyRun) {
        return (
            <>
                <div className="flex flex-col items-center justify-center gap-2 py-16 text-center text-muted">
                    <IconRocket className="text-2xl" />
                    <h3 className="mb-0">No features yet</h3>
                    <p className="max-w-lg text-sm">
                        Create a feature with an agent, or discover the features that already exist in a repository.
                        PostHog can own, monitor, and improve them over time.
                    </p>
                    {actionButtons}
                </div>
                <NewFeatureModal />
                <FeatureDiscoveryModal />
            </>
        )
    }

    return (
        <div className="flex flex-col gap-4 p-6">
            <div className="flex items-center justify-end">{actionButtons}</div>

            {activeDiscoveryRuns.map((run) => (
                <FeatureDiscoveryBanner key={run.id} run={run} />
            ))}
            {latestFailedRun && activeDiscoveryRuns.length === 0 && (
                <LemonBanner
                    type="error"
                    action={{
                        children: 'Try again',
                        onClick: () =>
                            retryDiscovery({ repository: latestFailedRun.repository, focus: latestFailedRun.focus }),
                        loading: discoveryRetryLoading,
                        'data-attr': 'feature-discovery-retry',
                    }}
                >
                    Feature discovery for <strong>{latestFailedRun.repository}</strong> failed.{' '}
                    {latestFailedRun.error || 'Check the GitHub connection and try again.'}
                </LemonBanner>
            )}
            {latestEmptyRun && activeDiscoveryRuns.length === 0 && (
                <LemonBanner type="info" action={{ children: 'Discover again', onClick: openDiscoveryModal }}>
                    Discovery found no features in <strong>{latestEmptyRun.repository}</strong>
                    {latestEmptyRun.focus ? ` for “${latestEmptyRun.focus}”` : ''}. Try a broader focus or another
                    repository.
                </LemonBanner>
            )}

            {stagedFeatures.length > 0 && (
                <section className="flex flex-col gap-2">
                    <div>
                        <h3 className="mb-0">Staged features</h3>
                        <p className="mb-0 text-sm text-muted">Review discovered reports before promoting them.</p>
                    </div>
                    {stagedFeatures.map((feature) => (
                        <LemonCard key={feature.id} className="flex flex-col gap-1">
                            <div className="flex items-center justify-between gap-2">
                                <LemonButton
                                    type="tertiary"
                                    size="small"
                                    className="-ml-2 font-semibold"
                                    to={urls.inboxReport('features', feature.id)}
                                >
                                    {feature.title || 'Untitled feature'}
                                </LemonButton>
                                <LemonTag type="highlight">Staged</LemonTag>
                            </div>
                            {feature.summary && (
                                <span className="line-clamp-2 text-sm text-muted">{feature.summary}</span>
                            )}
                            <TZLabel time={feature.updated_at} className="text-xs text-muted" />
                        </LemonCard>
                    ))}
                </section>
            )}

            {ownedFeatures.length > 0 && (
                <section className="flex flex-col gap-2">
                    {stagedFeatures.length > 0 && <h3 className="mb-0">Owned features</h3>}
                    {ownedFeatures.map((feature) => (
                        <LemonCard key={feature.id} className="flex flex-col gap-1">
                            <div className="flex items-center justify-between gap-2">
                                <LemonButton
                                    type="tertiary"
                                    size="small"
                                    className="-ml-2 font-semibold"
                                    to={urls.inboxReport('features', feature.id)}
                                >
                                    {feature.title || 'Untitled feature'}
                                </LemonButton>
                                {feature.is_planning ? (
                                    <LemonTag type="warning">Planning</LemonTag>
                                ) : (
                                    <LemonTag>{feature.status}</LemonTag>
                                )}
                            </div>
                            {feature.summary && (
                                <span className="line-clamp-2 text-sm text-muted">{feature.summary}</span>
                            )}
                            <TZLabel time={feature.updated_at} className="text-xs text-muted" />
                        </LemonCard>
                    ))}
                </section>
            )}
            <NewFeatureModal />
            <FeatureDiscoveryModal />
        </div>
    )
}
