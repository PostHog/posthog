import { useActions, useValues } from 'kea'

import { IconPlus, IconRocket, IconSearch } from '@posthog/icons'
import { LemonBadge, LemonBanner, LemonButton, LemonCard, LemonSkeleton, LemonTag, Link } from '@posthog/lemon-ui'

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
    const liveFeatures = features.filter((feature) => feature.feature_stage !== 'staged')
    const activeDiscoveryRuns = discoveryRuns.filter(
        (run) => run.discovery_status === 'queued' || run.discovery_status === 'running'
    )
    const latestFailedRun = discoveryRuns[0]?.discovery_status === 'failed' ? discoveryRuns[0] : undefined
    const latestEmptyRun =
        discoveryRuns[0]?.discovery_status === 'completed' && discoveryRuns[0].discovered_count === 0
            ? discoveryRuns[0]
            : undefined
    const featureColumns = [
        {
            key: 'staged',
            title: 'Staged features',
            description: 'Review discovered features before making them live.',
            emptyMessage: 'Discovered features will appear here.',
            features: stagedFeatures,
        },
        {
            key: 'live',
            title: 'Live features',
            description: 'Features PostHog monitors and improves over time.',
            emptyMessage: 'Promote a staged feature or create a new one.',
            features: liveFeatures,
        },
    ] as const

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

            <div className="grid grid-cols-1 items-start gap-4 lg:grid-cols-2">
                {featureColumns.map((column) => (
                    <section key={column.key} className="flex min-w-0 flex-col gap-2">
                        <div>
                            <div className="flex items-center gap-2">
                                <h3 className="mb-0">{column.title}</h3>
                                <LemonBadge.Number
                                    count={column.features.length}
                                    maxDigits={3}
                                    showZero
                                    size="small"
                                    status="muted"
                                />
                            </div>
                            <p className="mb-0 text-sm text-muted">{column.description}</p>
                        </div>

                        {column.features.length === 0 ? (
                            <LemonCard hoverEffect={false} className="border-dashed p-4">
                                <p className="mb-0 text-sm text-muted">{column.emptyMessage}</p>
                            </LemonCard>
                        ) : (
                            column.features.map((feature) => (
                                <Link
                                    key={feature.id}
                                    to={urls.inboxReport('features', feature.id)}
                                    className="block rounded text-inherit no-underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
                                >
                                    <LemonCard className="flex flex-col gap-1 p-4">
                                        <div className="flex items-start justify-between gap-2">
                                            <span className="min-w-0 break-words text-sm font-semibold leading-snug">
                                                {feature.title || 'Untitled feature'}
                                            </span>
                                            {column.key === 'live' &&
                                                (feature.is_planning ? (
                                                    <LemonTag type="warning">Planning</LemonTag>
                                                ) : (
                                                    <LemonTag>{feature.status}</LemonTag>
                                                ))}
                                        </div>
                                        {feature.summary && (
                                            <span className="line-clamp-2 text-sm text-muted">{feature.summary}</span>
                                        )}
                                        <TZLabel time={feature.updated_at} className="text-xs text-muted" />
                                    </LemonCard>
                                </Link>
                            ))
                        )}
                    </section>
                ))}
            </div>
            <NewFeatureModal />
            <FeatureDiscoveryModal />
        </div>
    )
}
