import { useActions, useValues } from 'kea'

import { IconFlag, IconWarning } from '@posthog/icons'
import { LemonDivider, LemonTag, Link, ProfilePicture, Tooltip } from '@posthog/lemon-ui'

import { CopyToClipboardInline } from 'lib/components/CopyToClipboard'
import { IconOpenInNew } from 'lib/lemon-ui/icons'
import { experimentLogic } from 'scenes/experiments/experimentLogic'
import { modalsLogic } from 'scenes/experiments/modalsLogic'
import { urls } from 'scenes/urls'

import { StatusTag } from 'products/experiments/frontend/components/StatusTag'
import { getExperimentStatus, isExperimentPaused } from 'products/experiments/frontend/experimentStatus'
import { RunningTimeConfigModal } from 'products/experiments/frontend/modals/RunningTimeConfigModal/RunningTimeConfigModal'

import { ExperimentConclusionCard } from './ExperimentConclusionCard'
import { ExperimentConclusionItem } from './ExperimentConclusionItem'
import { ExperimentDateRange } from './ExperimentDateRange'
import { ExperimentFlagCleanupStatus } from './ExperimentFlagCleanupStatus'
import { getExperimentMetaBarVisibility, getExperimentStatsSummary } from './experimentMetaBarUtils'
import { ExperimentRefreshButton } from './ExperimentRefreshButton'
import { ExperimentRemainingTime } from './ExperimentRemainingTime'

const PAUSED_TOOLTIP = 'This experiment is paused. The linked flag is disabled and no data is collected.'

function MetaDivider(): JSX.Element {
    return <LemonDivider vertical className="h-4 self-center" />
}

export function ExperimentMetaBar(): JSX.Element | null {
    const { experiment, statsMethod, isSingleVariantShipped, shippedVariantKey } = useValues(experimentLogic)
    const { openRunningTimeConfigModal } = useActions(modalsLogic)

    if (!experiment.feature_flag) {
        return null
    }

    const status = getExperimentStatus(experiment)
    const isPaused = isExperimentPaused(experiment)
    const visibility = getExperimentMetaBarVisibility(experiment)
    const stats = getExperimentStatsSummary(experiment, statsMethod)
    const { created_by } = experiment

    // The title keeps 8px of inner padding and the tabs pull up 16px, so the band sits midway only when pulled up 8px.
    return (
        <div className="flex flex-col gap-2 -mt-2" data-attr="experiment-meta-bar">
            <div className="flex flex-wrap items-center gap-x-3 gap-y-2 text-sm">
                <div className="flex items-center gap-1" data-attr="experiment-status">
                    {isPaused ? (
                        <Tooltip title={PAUSED_TOOLTIP}>
                            <StatusTag status={status} />
                        </Tooltip>
                    ) : (
                        <StatusTag status={status} />
                    )}
                    {isSingleVariantShipped && (
                        <Tooltip title={`Variant "${shippedVariantKey}" is rolled out to 100% of users`}>
                            <LemonTag type="completion" className="cursor-default">
                                <b className="uppercase">100% rollout</b>
                            </LemonTag>
                        </Tooltip>
                    )}
                </div>

                {visibility.showConclusion && (
                    <>
                        <MetaDivider />
                        <ExperimentConclusionItem />
                    </>
                )}

                <MetaDivider />

                <div className="flex items-center gap-1.5 min-w-0" data-attr="experiment-feature-flag">
                    {isPaused && (
                        <Tooltip title={PAUSED_TOOLTIP}>
                            <IconWarning className="text-danger text-base shrink-0" />
                        </Tooltip>
                    )}
                    <Tooltip title="Feature flag">
                        <IconFlag className="text-secondary text-base shrink-0" />
                    </Tooltip>
                    <CopyToClipboardInline className="font-normal truncate max-w-80" description="feature flag key">
                        {experiment.feature_flag.key}
                    </CopyToClipboardInline>
                    <Link
                        to={urls.featureFlag(experiment.feature_flag.id)}
                        target="_blank"
                        tooltip="Open feature flag"
                        className="flex items-center"
                    >
                        <IconOpenInNew className="text-base" />
                    </Link>
                </div>

                <MetaDivider />

                <Tooltip title={stats.description}>
                    <span className="flex items-center gap-1.5 cursor-default" data-attr="experiment-stats-method">
                        <span>{stats.method}</span>
                        <span className="text-secondary">·</span>
                        <span>{stats.level}</span>
                    </span>
                </Tooltip>

                {visibility.showDateRange && (
                    <>
                        <MetaDivider />
                        <ExperimentDateRange />
                    </>
                )}

                {visibility.showRemainingTime && (
                    <>
                        <MetaDivider />
                        <ExperimentRemainingTime experiment={experiment} onConfigure={openRunningTimeConfigModal} />
                    </>
                )}

                <div className="ml-auto flex items-center gap-2">
                    {visibility.showRefresh && <ExperimentRefreshButton experiment={experiment} />}
                    {created_by && (
                        <Tooltip title={`Created by ${created_by.first_name || created_by.email}`}>
                            <span className="flex items-center">
                                <ProfilePicture user={created_by} size="md" />
                            </span>
                        </Tooltip>
                    )}
                </div>
            </div>

            {visibility.showConclusion && <ExperimentConclusionCard />}

            {experiment.flag_cleanup_task_id && typeof experiment.id === 'number' && (
                <ExperimentFlagCleanupStatus experimentId={experiment.id} taskId={experiment.flag_cleanup_task_id} />
            )}

            {visibility.showRemainingTime && <RunningTimeConfigModal experiment={experiment} />}
        </div>
    )
}
